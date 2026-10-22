"""The shared event contract; timestamps are normalized at construction."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any

SOURCE_KINDS = {
    "claude_code": {"user_msg", "assistant_msg"},
    "codex": {"user_msg", "assistant_msg"},
    "browser_history": {"visit"},
    "capture": {"capture"},
    "git": {"commit"},
}


def utc_timestamp(value: str | datetime) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("事件时间必须包含时区。")
    # Fixed precision preserves chronological order in SQLite TEXT comparisons.
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Event:
    source: str
    source_id: str
    kind: str
    ts: str
    content: str = ""
    session_id: str | None = None
    project: str | None = None
    title: str | None = None
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    raw_ref: str = ""
    importance: str = "normal"

    def __post_init__(self) -> None:
        if self.source not in SOURCE_KINDS or self.kind not in SOURCE_KINDS[self.source]:
            raise ValueError("不支持的事件来源或类型。")
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError("source_id 不能为空。")
        for key in ("content", "raw_ref"):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f"{key} 必须是字符串。")
        for key in ("session_id", "project", "title", "url"):
            if getattr(self, key) is not None and not isinstance(getattr(self, key), str):
                raise ValueError(f"{key} 必须是字符串或 None。")
        if not isinstance(self.meta, dict):
            raise ValueError("meta 必须是字典。")
        if self.importance not in {"normal", "high"}:
            raise ValueError("importance 必须是 normal 或 high。")
        object.__setattr__(self, "ts", utc_timestamp(self.ts))
        if self.source == "capture":
            object.__setattr__(self, "importance", "high")

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.source_id}".encode("utf-8")).hexdigest()
