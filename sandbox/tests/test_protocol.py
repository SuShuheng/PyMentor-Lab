"""Authenticated, replay-safe, bounded Supervisor protocol tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pytest

from sandbox.protocol import (
    MAGIC,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    NonceCache,
    ProtocolAuthenticationError,
    ProtocolFrameError,
    canonical_json,
    decode_frame,
    encode_frame,
    sign_request,
    verify_request,
)

NOW = 1_752_700_010
TIMESTAMP = 1_752_700_000
SECRET = b"x" * 32
PATH = "/internal/v1/executions"


def _signed(body: bytes, *, nonce: str = "nonce-1") -> dict[str, str]:
    return sign_request(
        body,
        method="POST",
        path=PATH,
        secret=SECRET,
        timestamp=TIMESTAMP,
        nonce=nonce,
    )


def test_canonical_json_is_stable_unicode_and_rejects_nan() -> None:
    first = canonical_json({"z": "你好", "a": [2, 1]})
    second = canonical_json({"a": [2, 1], "z": "你好"})
    assert first == second == b'{"a":[2,1],"z":"\xe4\xbd\xa0\xe5\xa5\xbd"}'
    with pytest.raises(ValueError):
        canonical_json({"bad": float("nan")})


def test_signature_binds_method_path_timestamp_nonce_and_body() -> None:
    body = canonical_json({"run_id": "run_1", "source": "print(1)"})
    signed = _signed(body)
    verify_request(
        body,
        method="POST",
        path=PATH,
        headers=signed,
        secret=SECRET,
        now=NOW,
        nonces=NonceCache(ttl_seconds=60, capacity=100),
    )
    for changed_body, method, path in [
        (body + b" ", "POST", PATH),
        (body, "DELETE", PATH),
        (body, "POST", "/internal/v1/other"),
    ]:
        with pytest.raises(ProtocolAuthenticationError):
            verify_request(
                changed_body,
                method=method,
                path=path,
                headers=signed,
                secret=SECRET,
                now=NOW,
                nonces=NonceCache(60, 100),
            )


def test_verification_rejects_digest_signature_and_short_secret() -> None:
    body = canonical_json({"run_id": "run_1"})
    signed = _signed(body)
    bad_digest = {**signed, "x-sandbox-digest": "0" * 64}
    bad_signature = {**signed, "x-sandbox-signature": "0" * 64}
    for headers, secret in [
        (bad_digest, SECRET),
        (bad_signature, SECRET),
        (signed, b"short"),
    ]:
        with pytest.raises(ProtocolAuthenticationError):
            verify_request(
                body,
                method="POST",
                path=PATH,
                headers=headers,
                secret=secret,
                now=NOW,
                nonces=NonceCache(60, 100),
            )


def test_verification_rejects_timestamp_skew_nonce_syntax_and_replay() -> None:
    body = canonical_json({"run_id": "run_1"})
    cache = NonceCache(60, 100)
    signed = _signed(body)
    verify_request(
        body,
        method="POST",
        path=PATH,
        headers=signed,
        secret=SECRET,
        now=NOW,
        nonces=cache,
    )
    with pytest.raises(ProtocolAuthenticationError, match="nonce replay"):
        verify_request(
            body,
            method="POST",
            path=PATH,
            headers=signed,
            secret=SECRET,
            now=NOW + 1,
            nonces=cache,
        )
    stale = sign_request(
        body,
        method="POST",
        path=PATH,
        secret=SECRET,
        timestamp=TIMESTAMP - 31,
        nonce="stale",
    )
    with pytest.raises(ProtocolAuthenticationError, match="timestamp"):
        verify_request(
            body,
            method="POST",
            path=PATH,
            headers=stale,
            secret=SECRET,
            now=NOW,
            nonces=NonceCache(60, 100),
        )
    invalid_nonce = {**signed, "x-sandbox-nonce": "bad nonce"}
    with pytest.raises(ProtocolAuthenticationError, match="nonce"):
        verify_request(
            body,
            method="POST",
            path=PATH,
            headers=invalid_nonce,
            secret=SECRET,
            now=NOW,
            nonces=NonceCache(60, 100),
        )


def test_failed_authentication_does_not_consume_nonce() -> None:
    body = canonical_json({"run_id": "run_1"})
    cache = NonceCache(60, 100)
    signed = _signed(body, nonce="reusable-after-failure")
    with pytest.raises(ProtocolAuthenticationError):
        verify_request(
            body + b" ",
            method="POST",
            path=PATH,
            headers=signed,
            secret=SECRET,
            now=NOW,
            nonces=cache,
        )
    verify_request(
        body,
        method="POST",
        path=PATH,
        headers=signed,
        secret=SECRET,
        now=NOW,
        nonces=cache,
    )


def test_request_body_limit_is_enforced_before_digest_work() -> None:
    body = b"x" * (MAX_REQUEST_BYTES + 1)
    with pytest.raises(ProtocolAuthenticationError, match="body too large"):
        verify_request(
            body,
            method="POST",
            path=PATH,
            headers={
                "x-sandbox-timestamp": str(TIMESTAMP),
                "x-sandbox-nonce": "large",
                "x-sandbox-digest": hashlib.sha256(body).hexdigest(),
                "x-sandbox-signature": "0" * 64,
            },
            secret=SECRET,
            now=NOW,
            nonces=NonceCache(60, 100),
        )


def test_frame_round_trip_has_magic_and_exact_hex_length() -> None:
    value = {"ok": True, "message": "你好"}
    frame = encode_frame(value)
    body = canonical_json(value)
    assert frame.startswith(MAGIC)
    length_start = len(MAGIC)
    assert frame[length_start : length_start + 8] == f"{len(body):08x}".encode()
    assert decode_frame(frame) == value


@pytest.mark.parametrize(
    "mutate",
    [
        lambda frame: b"WRONG\n" + frame[len(MAGIC) :],
        lambda frame: frame[: len(MAGIC)] + b"zzzzzzzz" + frame[len(MAGIC) + 8 :],
        lambda frame: frame[: len(MAGIC)] + b"00000001" + frame[len(MAGIC) + 8 :],
        lambda frame: frame + b"trailing",
        lambda frame: frame + frame,
    ],
)
def test_frame_rejects_magic_length_mismatch_and_trailing_bytes(
    mutate: Callable[[bytes], bytes],
) -> None:
    with pytest.raises(ProtocolFrameError):
        decode_frame(mutate(encode_frame({"ok": True})))


def test_frame_rejects_non_object_duplicate_keys_and_nan() -> None:
    for raw in [b"[]", b'{"a":1,"a":2}', b'{"value":NaN}']:
        frame = MAGIC + f"{len(raw):08x}".encode() + b"\n" + raw
        with pytest.raises(ProtocolFrameError):
            decode_frame(frame)


def test_frame_enforces_maximum_response_size_on_encode_and_decode() -> None:
    with pytest.raises(ProtocolFrameError, match="too large"):
        encode_frame({"value": "x" * MAX_RESPONSE_BYTES})
    raw = json.dumps({"value": "x" * MAX_RESPONSE_BYTES}).encode()
    frame = MAGIC + f"{len(raw):08x}".encode() + b"\n" + raw
    with pytest.raises(ProtocolFrameError, match="too large"):
        decode_frame(frame)
