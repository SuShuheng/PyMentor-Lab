"""幂等引导：初始 System Admin、系统角色、demo 租户。

设计 §17.3.1：管理员账号由首次部署时的初始化脚本创建（环境变量指定）。
设计 §17.3.1：游客可一键体验（Demo Guest，独立演示租户，无需注册）。

幂等：重复执行无副作用。启动时调用（可由开关控制）。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import EmailStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.knowledge_seed import seed_published_course
from app.models import LearningPath, LearningPathStatus, TaskDefinition
from app.models.base import RoleName, TenantType, UserStatus
from app.models.identity import Tenant, User
from app.pathing import (
    PathProposal,
    StepProposal,
    ValidationContext,
    persist_validated_path,
    validate_path,
)
from app.security import hash_password
from app.services import (
    assign_role,
    ensure_roles_seeded,
    get_or_create_tenant,
    get_user_by_email,
    has_any_admin,
)
from app.task_compiler import CompileInput, compile_task_version

DEMO_TENANT_SLUG = "demo"
DEMO_GUEST_EMAIL = "guest@demo.pymentor.dev"
_LEGACY_DEMO_GUEST_EMAIL = "guest@demo.local"
_DEMO_COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
_DEMO_NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")


def ensure_demo_guest(db: Session, tenant: Tenant) -> User:
    """Ensure the reset-safe, endpoint-only guest identity exists."""

    guest = get_user_by_email(db, tenant_id=tenant.id, email=DEMO_GUEST_EMAIL)
    if guest is None:
        guest = get_user_by_email(
            db,
            tenant_id=tenant.id,
            email=_LEGACY_DEMO_GUEST_EMAIL,
        )
        if guest is not None:
            guest.email = DEMO_GUEST_EMAIL
    if guest is None:
        guest = User(
            tenant_id=tenant.id,
            email=DEMO_GUEST_EMAIL,
            # Demo access is issued only by POST /auth/demo. This intentionally
            # is not a valid password hash and cannot authenticate via /login.
            password_hash="demo-endpoint-only",
            status=UserStatus.ACTIVE,
            display_name="Demo Guest",
        )
        db.add(guest)
        db.flush()
    else:
        guest.status = UserStatus.ACTIVE
        guest.display_name = "Demo Guest"
        db.flush()
    assign_role(db, user_id=guest.id, role_name=RoleName.DEMO_GUEST.value)
    return guest


_settings = get_settings()


def _validate_initial_admin_email(email: str) -> None:
    """BE-029：用与 ``UserCreate.email`` 同源的 ``EmailStr`` 校验初始 admin 邮箱。

    抛 ``ValueError``（消息含 ``initial_admin_email`` 与 ``email`` 关键字，便于
    日志/启动错误定位）。复用 pydantic ``EmailStr`` 而非自写正则，避免与
    登录端 Pydantic 校验漂移。
    """
    from pydantic import TypeAdapter

    adapter: TypeAdapter[str] = TypeAdapter(EmailStr)
    try:
        adapter.validate_python(email)
    except ValidationError as exc:
        raise ValueError(f"initial_admin_email is not a valid email address: {email!r}") from exc


def bootstrap_initial_admin(db: Session) -> User | None:
    """创建初始 System Admin（若环境变量配置且尚无管理员）。

    幂等：已存在任意管理端角色用户时不重复创建。
    返回创建的 User，或 None（未配置/已存在）。

    BE-029：``PYMENTOR_INITIAL_ADMIN_EMAIL`` 必须是合法 email。V1.0 曾接受
    ``admin``（无 @-sign）并写入 users 表，但 ``POST /api/v1/auth/login`` 的
    Pydantic ``EmailStr`` 严格校验使该账号无法登录。这里在写入前用同一
    ``EmailStr`` 校验，让系统在启动时明确报错，而非静默生成不可用账号。
    """
    if not _settings.initial_admin_email or not _settings.initial_admin_password:
        return None

    # BE-029：与 UserCreate.email 同源的 EmailStr 校验，避免 bootstrap 写入
    # 一个登录端永远拒绝的账号。失败时抛 ValueError，由调用方记录并中止启动。
    _validate_initial_admin_email(_settings.initial_admin_email)

    # 幂等：已存在管理员则不创建。
    if has_any_admin(db):
        return None

    ensure_roles_seeded(db)
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    db.flush()

    # 若该邮箱已存在（如之前注册过），则提升为 admin 并激活。
    user = get_user_by_email(db, tenant_id=tenant.id, email=_settings.initial_admin_email)
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email=_settings.initial_admin_email,
            password_hash=hash_password(_settings.initial_admin_password),
            status=UserStatus.ACTIVE,
            display_name="Initial System Admin",
        )
        db.add(user)
        db.flush()
    else:
        user.status = UserStatus.ACTIVE
        db.flush()

    assign_role(db, user_id=user.id, role_name=RoleName.SYSTEM_ADMIN.value)
    db.commit()
    return user


def seed_demo_tenant(db: Session) -> None:
    """创建 demo 租户与 Demo Guest 用户（游客一键体验）。

    幂等：demo 租户与 guest 用户已存在时不重复创建。
    """
    ensure_roles_seeded(db)
    demo = get_or_create_tenant(
        db,
        slug=DEMO_TENANT_SLUG,
        name="Demo Tenant",
        tenant_type=TenantType.DEMO,
    )
    demo.type = TenantType.DEMO
    db.flush()
    ensure_demo_guest(db, demo)
    db.commit()


def seed_demo_learning_data(db: Session) -> None:
    """Publish one governed, reset-safe learning path and task for Demo Guest."""

    tenant = db.scalar(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
    if tenant is None:
        return
    guest = get_user_by_email(db, tenant_id=tenant.id, email=DEMO_GUEST_EMAIL)
    if guest is None:
        return
    definition = db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.tenant_id == tenant.id,
            TaskDefinition.course_id == _DEMO_COURSE_ID,
            TaskDefinition.key == "demo-loop-boundary",
        )
    )
    if definition is None:
        definition = TaskDefinition(
            tenant_id=tenant.id,
            course_id=_DEMO_COURSE_ID,
            node_id=_DEMO_NODE_ID,
            key="demo-loop-boundary",
            title="实现偶数求和函数",
        )
        db.add(definition)
        db.flush()
    compile_task_version(
        db,
        definition,
        CompileInput(
            prompt="实现 sum_even(numbers)，返回所有偶数之和；空列表返回 0。",
            tests_policy={
                "entrypoint": {"kind": "FUNCTION", "name": "sum_even"},
                "allowed_imports": ["math"],
                "visible": [
                    {
                        "id": "visible-basic",
                        "args": [[1, 2, 3, 4]],
                        "expected": 6,
                        "comparison": "EQUAL",
                        "transfer": False,
                    }
                ],
                "hidden": [
                    {
                        "id": "hidden-empty",
                        "args": [[]],
                        "expected": 0,
                        "comparison": "EQUAL",
                        "transfer": True,
                    }
                ],
            },
            hint_policy={
                "max_level": 3,
                "hints": [
                    {
                        "key": "iterate-values",
                        "level": 1,
                        "content": "逐个检查列表值是否能被 2 整除。",
                        "independence_cost": 10,
                    },
                    {
                        "key": "accumulate",
                        "level": 2,
                        "content": "使用从 0 开始的累计变量。",
                        "independence_cost": 20,
                    },
                    {
                        "key": "empty-list",
                        "level": 3,
                        "content": "空列表不会进入循环，因此返回初始累计值。",
                        "independence_cost": 30,
                    },
                ],
            },
            mastery_policy={
                "independence_min": 0.7,
                "transfer_min": 0.6,
                "max_hints_for_mastery": 1,
                "review_delay_days": 7,
            },
            resource_versions={},
            scenario_key="demo-sum-even-v1",
        ),
    )
    current_path = db.scalar(
        select(LearningPath).where(
            LearningPath.student_id == guest.id,
            LearningPath.course_id == _DEMO_COURSE_ID,
            LearningPath.status == LearningPathStatus.CURRENT,
        )
    )
    if current_path is None:
        validated = validate_path(
            PathProposal(steps=[StepProposal(node_id=_DEMO_NODE_ID, estimated_minutes=20)]),
            ValidationContext(
                daily_minutes=30,
                prerequisites={},
                completed_nodes=set(),
                due_reviews=[],
                mastery_policy_nodes={_DEMO_NODE_ID},
                resource_ready_nodes={_DEMO_NODE_ID},
                active_node_ids=set(),
                template_fallback_nodes=set(),
                forbidden_node_ids=set(),
            ),
        )
        persist_validated_path(
            db,
            tenant_id=tenant.id,
            student_id=guest.id,
            course_id=_DEMO_COURSE_ID,
            expected_version=0,
            validated=validated,
        )
    db.commit()


def run_bootstrap(db: Session) -> None:
    """执行全部引导步骤（启动时调用）。"""
    seed_published_course(db)
    ensure_roles_seeded(db)
    db.commit()
    bootstrap_initial_admin(db)
    seed_demo_tenant(db)
    seed_demo_learning_data(db)
