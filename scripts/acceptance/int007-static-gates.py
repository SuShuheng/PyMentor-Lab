"""Deterministic deployment/security gate for INT-007."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def check_compose() -> None:
    config = json.loads(run("docker", "compose", "config", "--format", "json"))
    services = config["services"]
    required = {"postgres", "redis", "minio", "api", "worker", "sandbox", "web", "admin"}
    missing = required - services.keys()
    assert not missing, f"missing Compose services: {sorted(missing)}"
    for name in required:
        assert services[name].get("healthcheck"), f"{name} has no healthcheck"
    for name in ("postgres", "redis", "minio", "api", "worker", "web", "admin"):
        for port in services[name].get("ports", []):
            assert port.get("host_ip") in {"127.0.0.1", "::1"}, (
                f"{name} publishes a non-loopback port: {port}"
            )
    assert services["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["api"]["depends_on"]["sandbox"]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"


def check_images_and_headers() -> None:
    for dockerfile in (ROOT / "infra").glob("*.Dockerfile"):
        text = dockerfile.read_text(encoding="utf-8")
        assert not re.search(r"(?mi)^FROM\s+\S+:latest(?:\s|$)", text), (
            f"unpinned latest tag in {dockerfile.relative_to(ROOT)}"
        )
    server = (ROOT / "infra" / "frontend-server.mjs").read_text(encoding="utf-8")
    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert header in server, f"frontend server omits {header}"
    assert "unsafe-eval" not in server


def check_environment_contract() -> None:
    sample = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in (
        "PYMENTOR_DATABASE_URL",
        "PYMENTOR_JWT_SECRET",
        "PYMENTOR_WORKER_INTERNAL_SECRET",
        "PYMENTOR_SANDBOX_SECRET",
        "PYMENTOR_OBJECT_STORE_SECRET_KEY",
        "PYMENTOR_CORS_ALLOWED_ORIGINS",
    ):
        assert re.search(rf"(?m)^{key}=", sample), f".env.example omits {key}"


def check_tracked_secrets_and_machine_paths() -> None:
    files = [ROOT / item for item in run("git", "ls-files").splitlines()]
    secret_patterns = {
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "live provider key": re.compile(r"\bsk-(?!test|example)[A-Za-z0-9_-]{24,}\b"),
    }
    machine_path = re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+/)")
    findings: list[str] = []
    for path in files:
        if not path.is_file() or path.suffix.lower() in {".png", ".ico", ".exe", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        for label, pattern in secret_patterns.items():
            if pattern.search(text):
                findings.append(f"{relative}: {label}")
        if relative.startswith("docs/") and machine_path.search(text):
            findings.append(f"{relative}: absolute machine path")
    assert not findings, "tracked sensitive material found:\n" + "\n".join(findings)


def main() -> None:
    check_compose()
    check_images_and_headers()
    check_environment_contract()
    check_tracked_secrets_and_machine_paths()
    print("INT-007 static gates: PASS")


if __name__ == "__main__":
    main()
