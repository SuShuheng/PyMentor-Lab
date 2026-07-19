"""Deterministic PostgreSQL fixtures and assertions for INT-002 browser E2E.

Credentials are read only from named environment variables. The command never
prints credentials, access tokens, email addresses, or refresh tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.bootstrap import DEMO_GUEST_EMAIL, DEMO_TENANT_SLUG  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ProfileDimension,
    ProfileDimensionScore,
    ProfileDispute,
    ProfileVersion,
    RoleName,
    Tenant,
    TenantType,
    User,
    UserSession,
    UserStatus,
)
from app.profile_projection import DimensionUpdate, project_profile  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import (  # noqa: E402
    assign_role,
    ensure_roles_seeded,
    get_or_create_tenant,
    get_user_by_email,
    get_user_roles,
)


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise SystemExit(f"required credential environment variable is unset: {name}")
    return value


def _print_result(**values: object) -> None:
    print(json.dumps(values, ensure_ascii=False, sort_keys=True))


def prepare_admin(args: argparse.Namespace) -> None:
    password = _secret(args.password_env)
    with SessionLocal() as db:
        ensure_roles_seeded(db)
        tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
        user = get_user_by_email(db, tenant_id=tenant.id, email=args.email)
        if user is None:
            user = User(
                tenant_id=tenant.id,
                email=args.email,
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
                display_name="INT-002 System Admin",
            )
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password(password)
            user.status = UserStatus.ACTIVE
            user.display_name = "INT-002 System Admin"
            db.flush()
        assign_role(db, user_id=user.id, role_name=RoleName.SYSTEM_ADMIN.value)
        db.commit()
    _print_result(admin_ready=True)


def seed_profile(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "default"))
        if tenant is None:
            raise SystemExit("default tenant does not exist")
        student = get_user_by_email(db, tenant_id=tenant.id, email=args.student_email)
        if student is None or student.status is not UserStatus.ACTIVE:
            raise SystemExit("active student fixture does not exist")
        if RoleName.STUDENT.value not in get_user_roles(db, student.id):
            raise SystemExit("fixture user does not have the STUDENT role")

        source_event_id = f"int002-evidence-{student.id}"
        existing = db.scalar(
            select(ProfileVersion).where(
                ProfileVersion.student_id == student.id,
                ProfileVersion.source_event_id == source_event_id,
            )
        )
        if existing is None:
            latest = db.scalar(
                select(ProfileVersion.version)
                .where(ProfileVersion.student_id == student.id)
                .order_by(ProfileVersion.version.desc())
                .limit(1)
            )
            dimensions = list(ProfileDimension)
            profile = project_profile(
                db,
                tenant_id=tenant.id,
                student_id=student.id,
                source_event_id=source_event_id,
                expected_version=latest or 0,
                updates=[
                    DimensionUpdate(
                        dimension=dimension.value,
                        scope_key="PYTHON_FOUNDATIONS",
                        score=round(0.42 + index * 0.05, 2),
                        confidence=round(0.71 + index * 0.03, 2),
                        support_level=index % 4,
                    )
                    for index, dimension in enumerate(dimensions)
                ],
            )
            db.commit()
        else:
            profile = existing
        dimension_count = db.scalar(
            select(func.count())
            .select_from(ProfileDimensionScore)
            .where(ProfileDimensionScore.profile_version_id == profile.id)
        )
    _print_result(
        profile_ready=True,
        profile_version=profile.version,
        dimension_count=dimension_count,
    )


def verify(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        default_tenant = db.scalar(select(Tenant).where(Tenant.slug == "default"))
        demo_tenant = db.scalar(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
        if default_tenant is None or demo_tenant is None:
            raise SystemExit("required tenant fixture is missing")

        admin = get_user_by_email(db, tenant_id=default_tenant.id, email=args.admin_email)
        student = get_user_by_email(
            db,
            tenant_id=default_tenant.id,
            email=args.student_email,
        )
        demo_guest = get_user_by_email(
            db,
            tenant_id=demo_tenant.id,
            email=DEMO_GUEST_EMAIL,
        )
        if admin is None or student is None or demo_guest is None:
            raise SystemExit("required user fixture is missing")

        profile = db.scalar(
            select(ProfileVersion)
            .where(
                ProfileVersion.tenant_id == default_tenant.id,
                ProfileVersion.student_id == student.id,
            )
            .order_by(ProfileVersion.version.desc())
            .limit(1)
        )
        if profile is None:
            raise SystemExit("student profile fixture is missing")

        dimensions = set(
            db.scalars(
                select(ProfileDimensionScore.dimension).where(
                    ProfileDimensionScore.profile_version_id == profile.id
                )
            )
        )
        dispute_count = db.scalar(
            select(func.count())
            .select_from(ProfileDispute)
            .where(
                ProfileDispute.tenant_id == default_tenant.id,
                ProfileDispute.student_id == student.id,
                ProfileDispute.profile_version_id == profile.id,
                ProfileDispute.reason == args.dispute_reason,
            )
        )
        student_session_count = db.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == student.id)
        )
        admin_session_count = db.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == admin.id)
        )
        demo_session_count = db.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.user_id == demo_guest.id)
        )

        checks = {
            "admin_active": admin.status is UserStatus.ACTIVE,
            "admin_role_exact": get_user_roles(db, admin.id) == [RoleName.SYSTEM_ADMIN.value],
            "student_active": student.status is UserStatus.ACTIVE,
            "student_role_exact": get_user_roles(db, student.id) == [RoleName.STUDENT.value],
            "standard_tenant": default_tenant.type is TenantType.STANDARD,
            "demo_tenant_isolated": demo_tenant.id != default_tenant.id
            and demo_tenant.type is TenantType.DEMO,
            "demo_role_exact": get_user_roles(db, demo_guest.id) == [RoleName.DEMO_GUEST.value],
            "eight_dimensions": dimensions == set(ProfileDimension),
            "evidence_linked": profile.source_event_id.startswith("int002-evidence-"),
            "dispute_persisted": dispute_count == 1,
            "refresh_sessions_persisted": min(
                student_session_count or 0,
                admin_session_count or 0,
                demo_session_count or 0,
            )
            >= 1,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise SystemExit(f"INT-002 authority checks failed: {', '.join(failed)}")
    _print_result(**checks, profile_version=profile.version)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-admin")
    prepare.add_argument("--email", required=True)
    prepare.add_argument("--password-env", required=True)
    prepare.set_defaults(handler=prepare_admin)

    profile = subparsers.add_parser("seed-profile")
    profile.add_argument("--student-email", required=True)
    profile.set_defaults(handler=seed_profile)

    authority = subparsers.add_parser("verify")
    authority.add_argument("--admin-email", required=True)
    authority.add_argument("--student-email", required=True)
    authority.add_argument("--dispute-reason", required=True)
    authority.set_defaults(handler=verify)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
