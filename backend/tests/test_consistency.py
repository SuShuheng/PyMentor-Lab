"""一致性基础设施测试：UoW 原子性、证据去重、Outbox 幂等、幂等性、乐观锁、日志脱敏。

需要真实 PostgreSQL（docker-compose）。通过 conftest 的 db_session fixture 隔离。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.evidence import list_evidence, record_evidence
from app.idempotency import get_or_create_idempotency, save_response
from app.locking import VersionConflictError, check_and_increment_version
from app.logging import redact_value
from app.models.base import UserStatus
from app.models.consistency import OutboxEvent
from app.models.identity import Tenant, User
from app.outbox import claim_unpublished, is_event_consumed, mark_published
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant
from app.uow import SqlAlchemyUnitOfWork


@pytest.fixture()
def tenant_and_student(db_session: Session) -> tuple[Tenant, User]:
    """创建一个租户和 ACTIVE 学生用于测试。"""
    tenant = get_or_create_tenant(db_session, slug="test-tenant", name="Test")
    db_session.flush()
    student = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email="student@test.local",
        password_hash=hash_password("ValidPass1!"),
    )
    student.status = UserStatus.ACTIVE
    db_session.commit()
    return tenant, student


# --------------------------------------------------------------------------- #
# Unit of Work 原子性
# --------------------------------------------------------------------------- #
class TestUnitOfWork:
    def test_state_and_outbox_commit_atomically(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """状态变更 + Outbox 事件一起提交。"""
        tenant, student = tenant_and_student
        with SqlAlchemyUnitOfWork(accept_session=db_session) as uow:
            assert uow.session is not None
            user = uow.session.get(User, student.id)
            assert user is not None
            user.display_name = "Updated"
            uow.publish(
                event_type="USER_UPDATED",
                aggregate_type="user",
                aggregate_id=str(student.id),
                tenant_id=tenant.id,
                trace_id="trc_test_1",
                payload={"field": "display_name"},
            )
            uow.commit()

        # 两者都持久化了。
        db_session.expire_all()
        updated_user = db_session.get(User, student.id)
        assert updated_user is not None
        assert updated_user.display_name == "Updated"
        events = list(db_session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(student.id)
            )
        ))
        assert len(events) == 1
        assert events[0].event_type == "USER_UPDATED"
        assert events[0].published is False

    def test_default_factory_reads_committed_state(self) -> None:
        """生产默认 SessionLocal 可读取其他已提交会话的数据。"""
        slug = f"uow-default-{uuid4().hex}"
        with SessionLocal() as setup_session:
            tenant = Tenant(slug=slug, name="UoW Default Factory")
            setup_session.add(tenant)
            setup_session.commit()
            tenant_id = tenant.id

        try:
            with SqlAlchemyUnitOfWork() as uow:
                assert uow.session is not None
                stored = uow.session.get(Tenant, tenant_id)
                assert stored is not None
                assert stored.slug == slug
        finally:
            with SessionLocal() as cleanup_session:
                stored = cleanup_session.get(Tenant, tenant_id)
                if stored is not None:
                    cleanup_session.delete(stored)
                    cleanup_session.commit()

    def test_rollback_discards_both(self, db_session: Session) -> None:
        """回滚时状态和 Outbox 一起撤销（永不出现「状态变了事件丢了」）。"""
        tenant = get_or_create_tenant(db_session, slug="rollback-tenant", name="Rollback")
        db_session.commit()
        with SqlAlchemyUnitOfWork(accept_session=db_session) as uow:
            assert uow.session is not None
            stored = uow.session.get(Tenant, tenant.id)
            assert stored is not None
            stored.name = "Changed"
            uow.publish(
                event_type="TENANT_UPDATED",
                aggregate_type="tenant",
                aggregate_id=str(tenant.id),
                tenant_id=tenant.id,
                trace_id="trc_rollback",
            )
            uow.rollback()

        db_session.expire_all()
        fresh = db_session.get(Tenant, tenant.id)
        assert fresh is not None
        assert fresh.name == "Rollback"  # 未变
        events = list(db_session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.trace_id == "trc_rollback"
            )
        ))
        assert len(events) == 0


# --------------------------------------------------------------------------- #
# 证据去重
# --------------------------------------------------------------------------- #
class TestEvidenceDedup:
    def test_invalid_evidence_uuid_filter_returns_validation_error(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """无效 UUID 查询参数必须进入稳定 422 错误信封。"""
        from collections.abc import Iterator

        from fastapi.testclient import TestClient

        from app.db import get_db
        from app.main import create_app
        from app.rbac import get_current_user

        _, student = tenant_and_student

        def _override_get_db() -> Iterator[Session]:
            yield db_session

        app = create_app()
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = lambda: student
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/api/v1/evidence", params={"course_id": "not-a-uuid"}
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_duplicate_event_id_returns_none(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """重复 event_id 的证据被去重（返回 None）。"""
        tenant, student = tenant_and_student
        event_id = f"evt_{uuid4().hex}"

        first = record_evidence(
            db_session,
            tenant_id=tenant.id,
            student_id=student.id,
            event_id=event_id,
            event_type="INTERACTION_ACCEPTED",
            trace_id="trc_1",
        )
        assert first is not None

        # 相同 event_id 再写 → 去重。
        duplicate = record_evidence(
            db_session,
            tenant_id=tenant.id,
            student_id=student.id,
            event_id=event_id,
            event_type="INTERACTION_ACCEPTED",
            trace_id="trc_2",
        )
        assert duplicate is None

        # 去重冲突只能回滚第二次插入，不能抹掉调用方事务中的首条证据。
        db_session.commit()
        evidence = list_evidence(
            db_session, tenant_id=tenant.id, student_id=student.id
        )
        assert [item.event_id for item in evidence] == [event_id]

    def test_list_evidence_filters_by_student(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """按学生查询证据。"""
        tenant, student = tenant_and_student
        for i in range(3):
            record_evidence(
                db_session,
                tenant_id=tenant.id,
                student_id=student.id,
                event_id=f"evt_filter_{i}",
                event_type="CODE_RUN_COMPLETED",
                trace_id="trc_list",
            )
        db_session.commit()

        results = list_evidence(db_session, tenant_id=tenant.id, student_id=student.id)
        assert len(results) == 3
        assert all(r.student_id == student.id for r in results)


# --------------------------------------------------------------------------- #
# Outbox 幂等消费
# --------------------------------------------------------------------------- #
class TestOutboxConsumer:
    def test_claim_and_mark_published(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """claim 获取未发布事件，mark_published 标记后不再获取。"""
        tenant, _ = tenant_and_student
        # 手动插入一条 Outbox 事件。
        event = OutboxEvent(
            tenant_id=tenant.id,
            event_type="TEST_EVENT",
            event_id=f"evt_ob_{uuid4().hex}",
            aggregate_type="test",
            aggregate_id="agg_1",
            trace_id="trc_ob",
            payload={},
        )
        db_session.add(event)
        db_session.commit()

        claimed = claim_unpublished(db_session, batch_size=10)
        assert any(e.event_id == event.event_id for e in claimed)

        mark_published(db_session, event)
        db_session.commit()

        # 已发布的不再被 claim。
        claimed_again = claim_unpublished(db_session, batch_size=10)
        assert not any(e.event_id == event.event_id for e in claimed_again)

    def test_is_event_consumed(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """幂等重放保护：已消费的 event_id 不重复处理。"""
        tenant, _ = tenant_and_student
        event_id = f"evt_consumed_{uuid4().hex}"
        event = OutboxEvent(
            tenant_id=tenant.id,
            event_type="TEST_EVENT",
            event_id=event_id,
            aggregate_type="test",
            aggregate_id="agg_2",
            trace_id="trc_c",
            payload={},
        )
        db_session.add(event)
        db_session.commit()

        assert not is_event_consumed(db_session, event_id)
        mark_published(db_session, event)
        db_session.commit()
        assert is_event_consumed(db_session, event_id)


# --------------------------------------------------------------------------- #
# 幂等性
# --------------------------------------------------------------------------- #
class TestIdempotency:
    def test_unfinished_key_remains_reserved(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """未完成请求的 key 保持占位，重复请求不能删除并重新执行。"""
        tenant, _ = tenant_and_student
        key = f"idem_pending_{uuid4().hex}"

        first = get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert first is None

        pending = get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert pending is not None
        assert pending.response_status is None

    def test_same_key_cannot_cross_tenant_scope(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """相同 key 不能向另一租户泄漏缓存响应。"""
        tenant, _ = tenant_and_student
        other_tenant = get_or_create_tenant(
            db_session, slug=f"idem-other-{uuid4().hex}", name="Other"
        )
        key = f"idem_scope_{uuid4().hex}"

        get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        save_response(
            db_session, key=key, response_status=200, response_body={"private": True}
        )
        db_session.commit()

        with pytest.raises(ValueError, match="scope conflict"):
            get_or_create_idempotency(
                db_session,
                key=key,
                tenant_id=other_tenant.id,
                endpoint="/api/v1/test",
            )

    def test_same_key_returns_cached(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """相同 key 第二次请求返回缓存记录。"""
        tenant, _ = tenant_and_student
        key = f"idem_{uuid4().hex}"

        # 第一次：无缓存，返回 None。
        result = get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert result is None
        save_response(db_session, key=key, response_status=200, response_body={"ok": True})
        db_session.commit()

        # 第二次：返回缓存。
        cached = get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert cached is not None
        assert cached.response_status == 200

    def test_cached_response_is_first_write_wins(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """已完成键的缓存结果不可被后续重放覆盖。"""
        tenant, _ = tenant_and_student
        key = f"idem_final_{uuid4().hex}"
        get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        save_response(
            db_session, key=key, response_status=200, response_body={"attempt": 1}
        )
        save_response(
            db_session, key=key, response_status=201, response_body={"attempt": 2}
        )
        db_session.commit()

        cached = get_or_create_idempotency(
            db_session, key=key, tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert cached is not None
        assert cached.response_status == 200
        assert cached.response_body == {"attempt": 1}

    def test_different_keys_independent(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """不同 key 独立处理。"""
        tenant, _ = tenant_and_student
        r1 = get_or_create_idempotency(
            db_session, key="key-a", tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        r2 = get_or_create_idempotency(
            db_session, key="key-b", tenant_id=tenant.id, endpoint="/api/v1/test"
        )
        assert r1 is None
        assert r2 is None


# --------------------------------------------------------------------------- #
# 乐观锁
# --------------------------------------------------------------------------- #
class TestOptimisticLocking:
    def test_correct_version_succeeds(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """正确 version 的更新成功并递增。"""
        _, student = tenant_and_student
        original_version = student.version
        new_version = check_and_increment_version(
            db_session, User, row_id=student.id, expected_version=original_version
        )
        db_session.commit()
        assert new_version == original_version + 1

    def test_wrong_version_conflicts(
        self, db_session: Session, tenant_and_student: tuple[Tenant, User]
    ) -> None:
        """错误 version 的更新抛冲突。"""
        _, student = tenant_and_student
        with pytest.raises(VersionConflictError):
            check_and_increment_version(
                db_session, User, row_id=student.id, expected_version=student.version + 999
            )


# --------------------------------------------------------------------------- #
# 日志脱敏
# --------------------------------------------------------------------------- #
class TestLoggingRedaction:
    def test_sensitive_value_redacted(self) -> None:
        assert redact_value("secret123", key="password") == "[REDACTED]"
        assert redact_value("tok_xxx", key="Authorization") == "[REDACTED]"

    def test_non_sensitive_preserved(self) -> None:
        assert redact_value("hello", key="message") == "hello"

    def test_nested_dict_redacted(self) -> None:
        data = {"user": "alice", "password": "secret", "nested": {"api_key": "k1"}}
        result = redact_value(data)
        assert result["password"] == "[REDACTED]"
        assert result["nested"]["api_key"] == "[REDACTED]"
        assert result["user"] == "alice"
