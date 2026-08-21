"""Versioned generated-launcher metadata and portable shim rendering."""

from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._models import AgentId, SessionReference
from ai_agent_launcher._runtime import resolve_worktree

_METADATA_PREFIX = "# ai-agent-launcher-metadata-v1: "


@dataclass(frozen=True)
class LauncherMetadata:
    """The agent-neutral state persisted in a generated launcher."""

    agent_id: AgentId
    worktree_dir: Path
    marker: str
    preparation_path: Path | None
    local_writable_dirs: tuple[Path, ...]
    session: SessionReference | None


def build_metadata(
    agent_id: AgentId,
    worktree_argument: str | Path,
    marker: str,
    preparation_argument: str | Path | None,
    local_writable_dirs: tuple[str, ...],
    session_id: str | None = None,
) -> LauncherMetadata:
    """Validate creation inputs and return canonical launcher metadata."""
    _validate_marker(marker)
    worktree_dir = resolve_worktree(str(worktree_argument))
    preparation_path = _preparation_path(preparation_argument)
    directories = _canonical_directories(local_writable_dirs)
    session = SessionReference(agent_id, session_id) if session_id is not None else None
    return LauncherMetadata(
        agent_id=agent_id,
        worktree_dir=worktree_dir,
        marker=marker,
        preparation_path=preparation_path,
        local_writable_dirs=directories,
        session=session,
    )


def validate_launcher_creation_inputs(
    marker: str,
    preparation_argument: str | Path | None,
    local_writable_dirs: tuple[str, ...],
) -> Path | None:
    """Validate launcher inputs that do not depend on an existing worktree."""
    _validate_marker(marker)
    preparation_path = _preparation_path(preparation_argument)
    _canonical_directories(local_writable_dirs)
    return preparation_path


def read_launcher(path_argument: str | Path) -> LauncherMetadata:
    """Read one supported versioned launcher without executing its contents."""
    path = Path(path_argument).expanduser()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise LauncherError(f"unable to read launcher {path}: {error}") from error
    encoded = next(
        (
            line.removeprefix(_METADATA_PREFIX)
            for line in content.splitlines()
            if line.startswith(_METADATA_PREFIX)
        ),
        None,
    )
    if encoded is None:
        raise LauncherError(f"launcher is not a supported generated launcher: {path}")
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise LauncherError(f"launcher metadata is invalid: {path}") from error
    if not isinstance(payload, dict):
        raise LauncherError(f"launcher metadata is invalid: {path}")
    return _metadata_from_payload(cast(dict[str, object], payload), path)


def write_launcher(
    path_argument: str | Path,
    metadata: LauncherMetadata,
    *,
    replace: bool = False,
    mode: int = 0o700,
) -> Path:
    """Atomically render a POSIX-shell launcher and return its canonical path."""
    path = Path(path_argument).expanduser()
    if path.exists() and not replace:
        raise LauncherError(f"launcher path already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise LauncherError(
            f"unable to create launcher directory {path.parent}: {error}"
        ) from error
    encoded = _encode_metadata(metadata)
    content = "\n".join(
        (
            "#!/bin/sh",
            "set -eu",
            metadata.marker,
            f"{_METADATA_PREFIX}{encoded}",
            'exec ai-agent-launcher launcher run --launcher "$0" -- "$@"',
            "",
        )
    )
    _atomic_write(path, content, mode)
    return path.resolve()


def replace_session(metadata: LauncherMetadata, session_id: str) -> LauncherMetadata:
    """Return metadata pinned to one opaque session reference."""
    return LauncherMetadata(
        agent_id=metadata.agent_id,
        worktree_dir=metadata.worktree_dir,
        marker=metadata.marker,
        preparation_path=metadata.preparation_path,
        local_writable_dirs=metadata.local_writable_dirs,
        session=SessionReference(metadata.agent_id, session_id),
    )


def with_local_directories(
    metadata: LauncherMetadata, directories: tuple[str, ...]
) -> LauncherMetadata:
    """Append caller directories after inherited entries with canonical deduplication."""
    merged = tuple(str(path) for path in metadata.local_writable_dirs) + directories
    return LauncherMetadata(
        agent_id=metadata.agent_id,
        worktree_dir=metadata.worktree_dir,
        marker=metadata.marker,
        preparation_path=metadata.preparation_path,
        local_writable_dirs=_canonical_directories(merged),
        session=metadata.session,
    )


def launcher_mode(path_argument: str | Path) -> int:
    """Return the portable Unix permission bits for a launcher."""
    path = Path(path_argument).expanduser()
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise LauncherError(f"unable to read launcher mode {path}: {error}") from error


def atomic_text_write(path_argument: str | Path, content: str, mode: int) -> None:
    """Atomically replace a UTF-8 file with explicitly requested permission bits."""
    _atomic_write(Path(path_argument).expanduser(), content, mode)


def _metadata_from_payload(payload: dict[str, object], path: Path) -> LauncherMetadata:
    expected_keys = {
        "agent_id",
        "format_version",
        "local_writable_dirs",
        "marker",
        "preparation_path",
        "session_id",
        "worktree_dir",
    }
    if set(payload) != expected_keys or payload.get("format_version") != 1:
        raise LauncherError(f"unsupported launcher metadata version: {path}")
    agent_value = payload.get("agent_id")
    worktree_value = payload.get("worktree_dir")
    marker = payload.get("marker")
    preparation = payload.get("preparation_path")
    session_id = payload.get("session_id")
    directories = payload.get("local_writable_dirs")
    if (
        not isinstance(agent_value, str)
        or not isinstance(worktree_value, str)
        or not isinstance(marker, str)
    ):
        raise LauncherError(f"launcher metadata is invalid: {path}")
    if preparation is not None and not isinstance(preparation, str):
        raise LauncherError(f"launcher metadata is invalid: {path}")
    if session_id is not None and not isinstance(session_id, str):
        raise LauncherError(f"launcher metadata is invalid: {path}")
    if not isinstance(directories, list):
        raise LauncherError(f"launcher metadata is invalid: {path}")
    directory_values: list[str] = []
    for directory in cast(list[object], directories):
        if not isinstance(directory, str):
            raise LauncherError(f"launcher metadata is invalid: {path}")
        directory_values.append(directory)
    try:
        return build_metadata(
            AgentId(agent_value),
            worktree_value,
            marker,
            preparation,
            tuple(directory_values),
            session_id,
        )
    except (LauncherError, ValueError) as error:
        raise LauncherError(f"launcher metadata is invalid: {path}: {error}") from error


def _encode_metadata(metadata: LauncherMetadata) -> str:
    payload: dict[str, object] = {
        "agent_id": str(metadata.agent_id),
        "format_version": 1,
        "local_writable_dirs": [str(path) for path in metadata.local_writable_dirs],
        "marker": metadata.marker,
        "preparation_path": str(metadata.preparation_path)
        if metadata.preparation_path is not None
        else None,
        "session_id": metadata.session.value if metadata.session is not None else None,
        "worktree_dir": str(metadata.worktree_dir),
    }
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )


def _validate_marker(marker: str) -> None:
    if not marker.startswith("#") or "\n" in marker or "\r" in marker:
        raise LauncherError("launcher marker must be one shell comment line")


def _preparation_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise LauncherError(f"preparation path is not an absolute executable file: {path}")
    return path.resolve()


def _canonical_directories(values: tuple[str, ...]) -> tuple[Path, ...]:
    directories: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise LauncherError(
                f"launcher local directory is not an absolute existing directory: {path}"
            )
        resolved = path.resolve()
        if resolved not in directories:
            directories.append(resolved)
    return tuple(directories)


def _atomic_write(path: Path, content: str, mode: int) -> None:
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    except OSError as error:
        raise LauncherError(f"unable to write {path}: {error}") from error
