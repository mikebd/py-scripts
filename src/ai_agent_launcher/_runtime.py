"""Agent-neutral runtime context and Git worktree validation."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._models import GitMetadataAccess


@dataclass(frozen=True)
class RunContext:
    """Inputs shared by every agent runtime invocation."""

    worktree_dir: Path
    configured_writable_dirs: tuple[str, ...]
    requested_writable_dirs: tuple[str, ...]
    passthrough_args: tuple[str, ...]
    git_metadata_access: GitMetadataAccess = GitMetadataAccess.WORKTREE


def resolve_worktree(worktree_argument: str | None) -> Path:
    """Resolve an existing directory to the top-level directory of its Git worktree."""
    candidate = Path.cwd() if worktree_argument is None else Path(worktree_argument).expanduser()
    if not candidate.is_dir():
        raise LauncherError(f"worktree is not a directory: {candidate}")

    resolved_candidate = candidate.resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(resolved_candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise LauncherError("git is required to run an agent in a worktree") from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or "directory is not inside a Git worktree"
        raise LauncherError(details) from error

    return Path(result.stdout.strip()).resolve()
