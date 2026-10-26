"""Shared collector contract; source-specific parsing stays in each collector."""

from dataclasses import dataclass, field
from datetime import timedelta
from logging import Logger
from typing import Protocol
from zoneinfo import ZoneInfo

from ..config import Config
from ..db import Database


@dataclass
class Context:
    config: Config
    db: Database
    logger: Logger
    timezone: ZoneInfo


@dataclass
class CollectResult:
    source: str
    inserted: int = 0
    skipped: int = 0  # Already-stored events, not filtered source records.
    warnings: int = 0
    errors: list[str] = field(default_factory=list)


class Collector(Protocol):
    name: str

    def collect(self, ctx: Context, *, backfill: timedelta | None = None,
                dry_run: bool = False) -> CollectResult: ...
