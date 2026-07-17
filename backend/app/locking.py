"""乐观锁：正式状态表的 version 字段并发冲突检测。

设计 §6.1：正式状态表含 version 字段；并发更新使用乐观锁。
更新时校验 version 匹配；不匹配 → VersionConflictError（调用方映射到 CONFLICT）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import Base


class VersionConflictError(Exception):
    """乐观锁版本冲突：另一事务已更新该行。"""


def check_and_increment_version(
    db: Session,
    model_class: type[Base],
    *,
    row_id: Any,
    expected_version: int,
) -> int:
    """乐观锁更新：校验 version 并递增。

    用 UPDATE ... WHERE id=? AND version=? 原子操作。
    如果 version 不匹配（行已被其他事务修改），rowcount=0 → 抛 VersionConflictError。
    返回新 version（expected_version + 1）。
    调用方负责 commit。
    """
    new_version = expected_version + 1
    # model_class 是 ORM 模型类，运行时有 id/version 列描述符。
    model_cls: Any = model_class
    stmt = (
        update(model_class)
        .where(model_cls.id == row_id, model_cls.version == expected_version)
        .values(version=new_version)
    )
    result = db.execute(stmt)
    # SQLAlchemy CursorResult 支持 rowcount 属性。
    rowcount: int = getattr(result, "rowcount", 0)
    if rowcount == 0:
        raise VersionConflictError(
            f"version conflict: expected {expected_version} for "
            f"{model_class.__name__} {row_id}"
        )
    db.flush()
    return new_version
