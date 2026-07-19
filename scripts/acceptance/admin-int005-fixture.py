"""Seed a disposable database for INT-005 real-browser acceptance.

The script requires an isolated database and test-only credentials supplied by
environment variables. Cleanup is performed by dropping that database; it must
never be pointed at a shared or production database.
"""

# ruff: noqa: E402 -- the standalone script resolves the repository-local backend first.

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.knowledge_seed import seed_published_course
from app.models import (
    AgentRun,
    AgentToolCall,
    AuditEvent,
    ProviderConfig,
    RoleName,
    User,
    UserStatus,
)
from app.observability import record_operational_log, record_provider_call
from app.providers import (
    ProviderType,
    decode_provider_master_key,
    encrypt_provider_secret,
    provider_secret_context,
)
from app.security import hash_password
from app.services import assign_role, create_student_user, get_or_create_tenant


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    database_url = required_env("PYMENTOR_DATABASE_URL")
    if "int005_browser" not in database_url:
        raise RuntimeError("refusing to seed a database not named for INT-005 browser acceptance")
    password = required_env("PYMENTOR_INT005_BROWSER_PASSWORD")
    master_key = decode_provider_master_key(required_env("PYMENTOR_PROVIDER_MASTER_KEY"))
    suffix = uuid4().hex
    engine = create_engine(database_url, future=True)
    try:
        with Session(engine) as db:
            seed_published_course(db)
            tenant = get_or_create_tenant(
                db,
                slug="default",
                name="INT-005 Browser Acceptance",
            )
            db.flush()
            admin = User(
                tenant_id=tenant.id,
                email=f"int-005-admin-{suffix}@example.edu",
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
                display_name="INT-005 System Admin",
            )
            db.add(admin)
            db.flush()
            assign_role(db, user_id=admin.id, role_name=RoleName.SYSTEM_ADMIN.value)
            students = []
            for label in ("Live Browser Student A", "Live Browser Student B"):
                student = create_student_user(
                    db,
                    tenant_id=tenant.id,
                    email=f"int-005-student-{uuid4().hex}@example.edu",
                    password_hash=hash_password(password),
                    student_no=f"INT005-{uuid4().hex[:8]}",
                    display_name=label,
                )
                student.status = UserStatus.ACTIVE
                students.append(student)
            db.flush()
            run = AgentRun(
                external_run_id=f"INT005-RUN-{suffix[:10]}",
                event_id=f"int-005-event-{suffix}",
                trace_id=f"int-005-trace-{suffix}",
                tenant_id=tenant.id,
                student_id=students[0].id,
                status="SUCCEEDED",
                route="resource",
                latest_sequence=2,
                checkpoint_thread_id=f"thread-{suffix}",
                latest_checkpoint_id=f"checkpoint-{suffix}",
                fallback_used=False,
                safe_input_snapshot={"api_key": "must-not-render", "summary": "bounded"},
                safe_output_snapshot={"result": "safe"},
            )
            db.add(run)
            db.flush()
            db.add(
                AgentToolCall(
                    tenant_id=tenant.id,
                    agent_run_id=run.id,
                    sequence=1,
                    node="resource",
                    tool_name="knowledge_search",
                    event_type="TOOL_COMPLETED",
                    status="SUCCEEDED",
                    argument_digest="2" * 64,
                    result_digest="3" * 64,
                    latency_ms=18,
                    retry_count=0,
                    occurred_at=datetime.now(UTC),
                )
            )
            provider_id = uuid4()
            provider_secret = "int-005-browser-provider-secret"
            db.add(
                ProviderConfig(
                    id=provider_id,
                    tenant_id=tenant.id,
                    provider_type=ProviderType.LLM,
                    vendor="INT-005 Browser Provider",
                    model="acceptance-model",
                    api_key_encrypted=encrypt_provider_secret(
                        provider_secret,
                        master_key,
                        provider_secret_context(tenant.id, provider_id),
                    ),
                    endpoint="https://provider.example.test/v1/models",
                    params={"temperature": 0.1},
                    enabled=True,
                )
            )
            db.flush()
            record_provider_call(
                db,
                tenant_id=tenant.id,
                provider_config_id=provider_id,
                provider_type=ProviderType.LLM,
                vendor="INT-005 Browser Provider",
                model="acceptance-model",
                operation="CHAT",
                outcome="SUCCEEDED",
                latency_ms=54,
                rate_limited=False,
                trace_id=f"int-005-metric-{suffix}",
            )
            record_operational_log(
                db,
                tenant_id=tenant.id,
                source="ERROR",
                level="ERROR",
                message="INT005_BROWSER_SAFE_ERROR",
                trace_id=f"int-005-log-{suffix}",
                context={"operation": "browser-acceptance"},
            )
            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_user_id=admin.id,
                    action="INT005_BROWSER_AUDIT",
                    resource_type="acceptance",
                    resource_id="int-005-browser",
                    trace_id=f"int-005-audit-{suffix}",
                    detail={"safe": True},
                )
            )
            db.commit()
            print(
                json.dumps(
                    {
                        "admin_email": admin.email,
                        "agent_run_id": run.external_run_id,
                        "student_id": str(students[0].id),
                        "tenant_id": str(tenant.id),
                    },
                    sort_keys=True,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
