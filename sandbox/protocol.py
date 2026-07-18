"""Authenticated request signing and strict single-frame sandbox protocol."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, cast

MAGIC = b"PYMENTOR_SANDBOX_V1\n"
MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
MAX_TIMESTAMP_SKEW_SECONDS = 30

_NONCE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_8 = re.compile(rb"[0-9a-fA-F]{8}\Z")


class ProtocolError(ValueError):
    pass


class ProtocolAuthenticationError(ProtocolError):
    pass


class ProtocolFrameError(ProtocolError):
    pass


class NonceCache:
    """Thread-safe, bounded replay cache using caller-supplied epoch seconds."""

    def __init__(self, ttl_seconds: int, capacity: int) -> None:
        if ttl_seconds < 1 or capacity < 1:
            raise ValueError("nonce cache ttl and capacity must be positive")
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._values: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def check_and_store(self, nonce: str, *, now: int) -> bool:
        """Return False for a live replay; otherwise consume and return True."""

        with self._lock:
            expired = [key for key, expiry in self._values.items() if expiry <= now]
            for key in expired:
                self._values.pop(key, None)
            if nonce in self._values:
                return False
            while len(self._values) >= self.capacity:
                self._values.popitem(last=False)
            self._values[nonce] = now + self.ttl_seconds
            return True


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def signature_message(method: str, path: str, timestamp: int, nonce: str, digest: str) -> bytes:
    try:
        return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtocolAuthenticationError("signature fields must be ASCII") from exc


def _validate_signing_inputs(*, secret: bytes, path: str, nonce: str) -> None:
    if len(secret) < 32:
        raise ProtocolAuthenticationError("shared secret must contain at least 32 bytes")
    if not path.startswith("/") or "?" in path or "#" in path:
        raise ProtocolAuthenticationError("path must be normalized")
    if _NONCE.fullmatch(nonce) is None:
        raise ProtocolAuthenticationError("invalid nonce")


def sign_request(
    body: bytes,
    *,
    method: str,
    path: str,
    secret: bytes,
    timestamp: int,
    nonce: str,
) -> dict[str, str]:
    _validate_signing_inputs(secret=secret, path=path, nonce=nonce)
    if len(body) > MAX_REQUEST_BYTES:
        raise ProtocolAuthenticationError("request body too large")
    digest = hashlib.sha256(body).hexdigest()
    signature = hmac.new(
        secret,
        signature_message(method, path, timestamp, nonce, digest),
        hashlib.sha256,
    )
    return {
        "x-sandbox-timestamp": str(timestamp),
        "x-sandbox-nonce": nonce,
        "x-sandbox-digest": digest,
        "x-sandbox-signature": signature.hexdigest(),
    }


def verify_request(
    body: bytes,
    *,
    method: str,
    path: str,
    headers: Mapping[str, str],
    secret: bytes,
    now: int,
    nonces: NonceCache,
) -> None:
    if len(body) > MAX_REQUEST_BYTES:
        raise ProtocolAuthenticationError("request body too large")
    lowered = {key.lower(): value for key, value in headers.items()}
    try:
        timestamp_text = lowered["x-sandbox-timestamp"]
        nonce = lowered["x-sandbox-nonce"]
        supplied_digest = lowered["x-sandbox-digest"]
        supplied_signature = lowered["x-sandbox-signature"]
    except KeyError as exc:
        raise ProtocolAuthenticationError("missing authentication header") from exc
    _validate_signing_inputs(secret=secret, path=path, nonce=nonce)
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise ProtocolAuthenticationError("invalid timestamp") from exc
    if abs(now - timestamp) > MAX_TIMESTAMP_SKEW_SECONDS:
        raise ProtocolAuthenticationError("timestamp outside allowed skew")
    if _HEX_64.fullmatch(supplied_digest) is None or _HEX_64.fullmatch(supplied_signature) is None:
        raise ProtocolAuthenticationError("invalid digest or signature encoding")

    actual_digest = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(supplied_digest, actual_digest):
        raise ProtocolAuthenticationError("body digest mismatch")
    expected_signature = hmac.new(
        secret,
        signature_message(method, path, timestamp, nonce, actual_digest),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise ProtocolAuthenticationError("request signature mismatch")
    if not nonces.check_and_store(nonce, now=now):
        raise ProtocolAuthenticationError("nonce replay")


def encode_frame(value: object, *, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    body = canonical_json(value)
    if len(body) > max_bytes:
        raise ProtocolFrameError("frame body too large")
    return MAGIC + f"{len(body):08x}".encode("ascii") + b"\n" + body


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolFrameError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ProtocolFrameError(f"invalid JSON constant {value}")


def decode_frame(frame: bytes, *, max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    if not frame.startswith(MAGIC):
        raise ProtocolFrameError("invalid frame magic")
    length_start = len(MAGIC)
    length_end = length_start + 8
    if len(frame) < length_end + 1 or frame[length_end : length_end + 1] != b"\n":
        raise ProtocolFrameError("invalid frame length header")
    length_text = frame[length_start:length_end]
    if _HEX_8.fullmatch(length_text) is None:
        raise ProtocolFrameError("invalid frame length encoding")
    declared = int(length_text, 16)
    if declared > max_bytes:
        raise ProtocolFrameError("frame body too large")
    body_start = length_end + 1
    if len(frame) != body_start + declared:
        raise ProtocolFrameError("frame declared length mismatch or trailing bytes")
    body = frame[body_start:]
    try:
        parsed = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ProtocolFrameError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolFrameError("invalid frame JSON") from exc
    if not isinstance(parsed, dict):
        raise ProtocolFrameError("frame JSON must be an object")
    return cast(dict[str, Any], parsed)
