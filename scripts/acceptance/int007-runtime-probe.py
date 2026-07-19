"""Bounded live-service and latency probe for the INT-007 Compose stack."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass

API = os.getenv("PYMENTOR_API_URL", "http://127.0.0.1:8000")
WEB = os.getenv("PYMENTOR_WEB_URL", "http://127.0.0.1:4173")
ADMIN = os.getenv("PYMENTOR_ADMIN_URL", "http://127.0.0.1:4174")
WORKER = os.getenv("PYMENTOR_WORKER_URL", "http://127.0.0.1:8081")


@dataclass(frozen=True)
class TimedResponse:
    elapsed_ms: float
    body: bytes
    headers: object
    status: int


def request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> TimedResponse:
    data = json.dumps(body).encode() if body is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    started = time.perf_counter()
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=request_headers, method=method),
        timeout=timeout,
    ) as response:
        payload = response.read()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return TimedResponse(elapsed_ms, payload, response.headers, response.status)


def assert_bounded(name: str, response: TimedResponse, maximum_ms: float) -> None:
    assert response.status == 200, f"{name} returned HTTP {response.status}"
    assert response.elapsed_ms <= maximum_ms, (
        f"{name} exceeded {maximum_ms:.0f} ms: {response.elapsed_ms:.1f} ms"
    )
    print(f"{name}={response.elapsed_ms:.1f}ms")


def main() -> None:
    assert_bounded("api_ready", request(f"{API}/ready"), 1500)
    assert_bounded("worker_ready", request(f"{WORKER}/ready"), 1500)
    web = request(f"{WEB}/login")
    assert_bounded("web_login", web, 2000)
    assert "Content-Security-Policy" in web.headers
    assert_bounded("admin_login", request(f"{ADMIN}/login"), 2000)

    login = request(f"{API}/api/v1/auth/demo", method="POST", body={})
    assert_bounded("demo_login", login, 2000)
    token = json.loads(login.body)["access_token"]
    authorization = {"Authorization": f"Bearer {token}"}
    today = request(f"{API}/api/v1/learning/today", headers=authorization)
    assert_bounded("learning_today", today, 1500)
    items = json.loads(today.body)
    assert items, "demo bootstrap did not publish a today item"

    path = request(f"{API}/api/v1/paths/current", headers=authorization)
    assert_bounded("current_path", path, 1500)
    path_body = json.loads(path.body)
    node_id = path_body["steps"][0]["node_id"]
    course_id = path_body["course_id"]
    chat = request(
        f"{API}/api/v1/chat/completions",
        method="POST",
        headers={"Accept": "text/event-stream", **authorization},
        body={
            "course_id": course_id,
            "messages": [{"content": "Explain the current boundary.", "role": "user"}],
            "node_id": node_id,
            "stream": True,
        },
    )
    assert_bounded("sse_complete", chat, 2000)
    stream = chat.body.decode()
    assert "event: error" in stream and "event: done" in stream
    assert "PROVIDER_UNAVAILABLE" in stream
    assert "No tutoring stream Provider is configured" not in stream
    print("INT-007 runtime probe: PASS")


if __name__ == "__main__":
    main()
