"""结构化 JSON 日志 + trace_id 传播 + 敏感字段脱敏。

设计 §20.1：每条请求/作业携带 trace_id、user_id、task_id、agent_run_id、job_id、event_id。
设计 §20：日志不泄漏密钥/raw prompt（PRD REQ-P0-021：日志脱敏）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

# 需要脱敏的字段名（大小写不敏感匹配）。
SENSITIVE_KEYS = frozenset({
    "password",
    "password_hash",
    "api_key",
    "api_key_encrypted",
    "secret",
    "jwt_secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "raw_prompt",
    "credential",
})


def redact_value(value: Any, key: str = "") -> Any:
    """递归脱敏：敏感字段的值替换为 [REDACTED]。"""
    key_lower = key.lower()
    if key_lower in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


class RedactingJsonFormatter(logging.Formatter):
    """JSON 格式化器，自动脱敏敏感字段，注入 trace_id 等上下文。"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 从 LogRecord 的 extra 字段注入上下文（trace_id/user_id 等）。
        for attr in ("trace_id", "user_id", "task_id", "agent_run_id", "job_id", "event_id"):
            value = getattr(record, attr, None)
            if value is not None:
                log_entry[attr] = value

        # 脱敏任何附带的 data 字段。
        data = getattr(record, "data", None)
        if data is not None:
            log_entry["data"] = redact_value(data)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """配置根 logger 使用 RedactingJsonFormatter。"""
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_context(
    logger: logging.Logger,
    level: int,
    msg: str,
    *,
    trace_id: str | None = None,
    user_id: str | None = None,
    task_id: str | None = None,
    agent_run_id: str | None = None,
    job_id: str | None = None,
    event_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """带上下文的结构化日志（trace_id 等注入 LogRecord extra）。"""
    extra: dict[str, Any] = {}
    if trace_id is not None:
        extra["trace_id"] = trace_id
    if user_id is not None:
        extra["user_id"] = user_id
    if task_id is not None:
        extra["task_id"] = task_id
    if agent_run_id is not None:
        extra["agent_run_id"] = agent_run_id
    if job_id is not None:
        extra["job_id"] = job_id
    if event_id is not None:
        extra["event_id"] = event_id
    if data is not None:
        extra["data"] = data
    logger.log(level, msg, extra=extra)
