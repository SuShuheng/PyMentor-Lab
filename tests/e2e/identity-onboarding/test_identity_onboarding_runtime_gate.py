from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_browser_origins_can_reach_the_real_api() -> None:
    client = TestClient(create_app())
    try:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Method": "POST",
                "Origin": "http://127.0.0.1:4173",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_demo_login_and_disputable_profile_are_public_contracts() -> None:
    schema = create_app().openapi()

    assert "/api/v1/auth/demo" in schema["paths"]
    profile = schema["components"]["schemas"]["ProfileSnapshot"]
    assert "id" in profile["properties"]
    assert "id" in profile["required"]


def test_student_runtime_uses_demo_and_profile_sdk_calls() -> None:
    auth_api = _read("apps/web/src/features/auth/auth-api.ts")
    onboarding = _read("apps/web/src/features/onboarding/onboarding-pages.tsx")

    assert "demoLoginApiV1AuthDemoPost" in auth_api
    assert "服务器尚未提供演示账号登录接口" not in auth_api
    assert "getCurrentProfileApiV1ProfilesCurrentGet" in onboarding
    assert "disputeProfileApiV1ProfilesDisputesPost" in onboarding
    assert "const profileDimensions = [" not in onboarding


def test_admin_runtime_uses_registration_review_sdk_calls() -> None:
    operations = _read("apps/admin/src/features/operations/admin-operation-pages.tsx")

    assert "listPendingApiV1AdminRegistrationsPendingGet" in operations
    assert "approveRegistrationApiV1AdminRegistrationsUserIdApprovePost" in operations
    assert "rejectRegistrationApiV1AdminRegistrationsUserIdRejectPost" in operations
    assert "const initialRegistrations = [" not in operations
