"""Shared project naming; repository-aware resolution follows in M2."""

from pathlib import Path


def resolve_project(cwd: str | None) -> str | None:
    return Path(cwd).name if cwd else None
