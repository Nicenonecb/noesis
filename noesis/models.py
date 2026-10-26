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
    # M0 stored only the hashed ID. Query results must preserve that identity.
    _stored_id: str | None = field(default=None, repr=False, compare=False)

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
        return self._stored_id or hashlib.sha1(f"{self.source}|{self.source_id}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Session:
    source: str
    session_id: str
    started_at: str
    ended_at: str
    project: str | None = None
    cwd: str | None = None
    title: str = ""
    n_user: int = 0
    n_assistant: int = 0
    raw_path: str = ""

    def __post_init__(self):
        if self.source not in {"claude_code", "codex"} or not self.session_id:
            raise ValueError("不支持的会话来源或会话 ID。")
        for name in ("started_at", "ended_at"):
            object.__setattr__(self, name, utc_timestamp(getattr(self, name)))
        if self.ended_at < self.started_at or min(self.n_user, self.n_assistant) < 0:
            raise ValueError("会话时间或消息数不正确。")

    @property
    def id(self):
        return hashlib.sha1(f"{self.source}|{self.session_id}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SearchHit:
    event: Event
    snippet: str


@dataclass(frozen=True)
class DomainStat:
    domain: str
    visits: int
    duration_seconds: float
    pages: list[dict]


@dataclass(frozen=True)
class ProjectTime:
    project: str
    minutes: int


@dataclass(frozen=True)
class SourceStats:
    source: str
    total: int
    today_inserted: int
    last_run: dict | None


@dataclass(frozen=True)
class Stats:
    sources: list[SourceStats]
