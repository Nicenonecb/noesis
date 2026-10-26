"""Shared project naming; repository-aware resolution follows in M2."""

from pathlib import Path


def resolve_project(cwd: str | None, repos=()) -> str | None:
    if not cwd:
        return None
    path=Path(cwd).resolve()
    for repo in sorted(repos,key=lambda item:len(item['path']),reverse=True):
        if path.is_relative_to(repo['path']):
            return repo['name']
    # Linked worktrees may not be descendants of the canonical repository.
    if path.is_dir() and repos:
        from .collectors.git_log import repo_info
        import subprocess
        try:
            common=repo_info(path)['common_dir']
            match=next((repo for repo in repos if repo['common_dir']==common),None)
            if match:
                return match['name']
        except (OSError,subprocess.SubprocessError):
            pass
    return path.name
