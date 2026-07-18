"""幂等引导：初始 System Admin、系统角色、demo 租户。

设计 §17.3.1：管理员账号由首次部署时的初始化脚本创建（环境变量指定）。
设计 §17.3.1：游客可一键体验（Demo Guest，独立演示租户，无需注册）。

幂等：重复执行无副作用。启动时调用（可由开关控制）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.knowledge_seed import seed_published_course
from app.models.base import RoleName, TenantType, UserStatus
from app.models.identity import User
from app.security import hash_password
from app.services import (
    assign_role,
    ensure_roles_seeded,
    get_or_create_tenant,
    get_user_by_email,
    has_any_admin,
)

_settings = get_settings()


def bootstrap_initial_admin(db: Session) -> User | None:
    """创建初始 System Admin（若环境变量配置且尚无管理员）。

    幂等：已存在任意管理端角色用户时不重复创建。
    返回创建的 User，或 None（未配置/已存在）。
    """
    if not _settings.initial_admin_email or not _settings.initial_admin_password:
        return None

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
    demo = get_or_create_tenant(db, slug="demo", name="Demo Tenant", tenant_type=TenantType.DEMO)
    db.flush()

    # Demo Guest 用户（DEMO_GUEST 角色，ACTIVE 可直接登录体验）。
    guest_email = "guest@demo.local"
    guest = get_user_by_email(db, tenant_id=demo.id, email=guest_email)
    if guest is None:
        guest = User(
            tenant_id=demo.id,
            email=guest_email,
            password_hash=hash_password("demo-guest-pwd"),
            status=UserStatus.ACTIVE,
            display_name="Demo Guest",
        )
        db.add(guest)
        db.flush()
        assign_role(db, user_id=guest.id, role_name=RoleName.DEMO_GUEST.value)

    db.commit()


def run_bootstrap(db: Session) -> None:
    """执行全部引导步骤（启动时调用）。"""
    seed_published_course(db)
    ensure_roles_seeded(db)
    db.commit()
    bootstrap_initial_admin(db)
    seed_demo_tenant(db)
