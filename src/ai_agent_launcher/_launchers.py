"""Versioned generated-launcher metadata and portable shim rendering."""

from __future__ import annotations

import base64
import json
import os
import shlex
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._models import AgentId, GitMetadataAccess, SessionReference
from ai_agent_launcher._runtime import resolve_worktree

_METADATA_FORMAT_VERSION = 1
_METADATA_PREFIX = f"# ai-agent-launcher-metadata-v{_METADATA_FORMAT_VERSION}: "
_INSPECTION_HINT = (
    "# Inspect metadata with: ai-agent-launcher launcher describe --launcher <launcher-path>"
)

type MetadataExtensionValue = str | int | float | bool | None
type MetadataExtensions = dict[str, dict[str, MetadataExtensionValue]]


@dataclass(frozen=True)
class LauncherMetadata:
    """Validated launcher state used by lifecycle operations."""

    agent_id: AgentId
    worktree_dir: Path
    preparation_path: Path | None
    local_writable_dirs: tuple[Path, ...]
    session: SessionReference | None
    extensions: MetadataExtensions | None


@dataclass(frozen=True)
class LauncherArtifactMetadata:
    """Structurally valid launcher state without runtime filesystem validation."""

    format_version: int
    agent_id: AgentId
    worktree_dir: Path
    preparation_path: Path | None
    local_writable_dirs: tuple[Path, ...]
    session: SessionReference | None
    extensions: MetadataExtensions | None


def build_metadata(
    agent_id: AgentId,
    worktree_argument: str | Path,
    preparation_argument: str | Path | None,
    local_writable_dirs: tuple[str, ...],
    session_id: str | None = None,
    extensions: MetadataExtensions | None = None,
    *,
    validate_preparation: bool = True,
) -> LauncherMetadata:
    """Validate creation inputs and return canonical launcher metadata."""
    worktree_dir = resolve_worktree(str(worktree_argument))
    preparation_path = resolve_preparation_path(
        preparation_argument,
        worktree_dir,
        require_executable=validate_preparation,
    )
    directories = _canonical_directories(local_writable_dirs)
    session = SessionReference(agent_id, session_id) if session_id is not None else None
    return LauncherMetadata(
        agent_id=agent_id,
        worktree_dir=worktree_dir,
        preparation_path=preparation_path,
        local_writable_dirs=directories,
        session=session,
        extensions=_validated_extensions(extensions) if extensions is not None else None,
    )


def validate_launcher_creation_inputs(
    preparation_argument: str | Path | None,
    local_writable_dirs: tuple[str, ...],
) -> None:
    """Validate worktree-creation inputs that do not need the target to exist."""
    if preparation_argument is not None:
        _expanded_preparation_path(preparation_argument)
    _canonical_directories(local_writable_dirs)


def read_launcher(path_argument: str | Path) -> LauncherMetadata:
    """Read one supported versioned launcher without executing its contents."""
    artifact = read_launcher_artifact(path_argument)
    path = Path(path_argument).expanduser()
    try:
        return build_metadata(
            artifact.agent_id,
            artifact.worktree_dir,
            artifact.preparation_path,
            tuple(str(directory) for directory in artifact.local_writable_dirs),
            artifact.session.value if artifact.session is not None else None,
            artifact.extensions,
            validate_preparation=False,
        )
    except (LauncherError, ValueError) as error:
        raise LauncherError(f"launcher metadata is invalid: {path}: {error}") from error


def read_launcher_artifact(path_argument: str | Path) -> LauncherArtifactMetadata:
    """Read supported persisted state without checking its current environment."""
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
    return _artifact_from_payload(cast(dict[str, object], payload), path)


def describe_launcher(
    path_argument: str | Path, metadata: LauncherArtifactMetadata | None = None
) -> str:
    """Return a human-readable description of a supported launcher artifact."""
    path = Path(path_argument).expanduser()
    if metadata is None:
        metadata = read_launcher_artifact(path)
    session = metadata.session.value if metadata.session is not None else "unpinned"
    preparation = (
        str(metadata.preparation_path) if metadata.preparation_path is not None else "none"
    )
    lines = [
        f"launcher: {path}",
        f"format version: {metadata.format_version}",
        f"agent: {metadata.agent_id}",
        f"worktree: {metadata.worktree_dir}",
        f"session: {session}",
        f"preparation: {preparation}",
        _git_metadata_access_description(metadata),
    ]
    if metadata.extensions:
        lines.append("metadata extensions:")
        for namespace in sorted(metadata.extensions):
            for name in sorted(metadata.extensions[namespace]):
                value = metadata.extensions[namespace][name]
                lines.append(f"  - {namespace}.{name}: {json.dumps(value, sort_keys=True)}")
    else:
        lines.append("metadata extensions: none")
    if metadata.local_writable_dirs:
        lines.append("local writable directories:")
        lines.extend(f"  - {directory}" for directory in sorted(metadata.local_writable_dirs))
    else:
        lines.append("local writable directories: none")
    return "\n".join(lines) + "\n"


def write_launcher(
    path_argument: str | Path,
    metadata: LauncherMetadata,
    *,
    replace: bool = False,
    mode: int = 0o700,
) -> Path:
    """Atomically render a POSIX-shell launcher and return its canonical path."""
    path = _prepare_launcher_target(path_argument, replace=replace)
    encoded = _encode_metadata(metadata)
    content = "\n".join(
        (
            "#!/bin/sh",
            "set -eu",
            _INSPECTION_HINT,
            f"{_METADATA_PREFIX}{encoded}",
            'case "$0" in',
            '  /*) launcher_path="$0" ;;',
            (
                '  *) launcher_path="$(CDPATH=\'\' cd -P "$(dirname "$0")" && '
                'pwd)/$(basename "$0")" ;;'
            ),
            "esac",
            f"cd {shlex.quote(str(metadata.worktree_dir))}",
            'exec ai-agent-launcher launcher run --launcher "$launcher_path" -- "$@"',
            "",
        )
    )
    _atomic_write(path, content, mode)
    return path.resolve()


def preflight_launcher_target(path_argument: str | Path) -> None:
    """Reject an unavailable new target before an irreversible lifecycle operation."""
    path = _prepare_launcher_target(path_argument, replace=False)
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}."
        ) as temporary:
            Path(temporary.name).chmod(0o700)
    except OSError as error:
        raise LauncherError(f"unable to write {path}: {error}") from error


def replace_session(metadata: LauncherMetadata, session_id: str) -> LauncherMetadata:
    """Return metadata pinned to one opaque session reference."""
    return replace(metadata, session=SessionReference(metadata.agent_id, session_id))


def with_local_directories(
    metadata: LauncherMetadata, directories: tuple[str, ...]
) -> LauncherMetadata:
    """Append caller directories after inherited entries with canonical deduplication."""
    merged = tuple(str(path) for path in metadata.local_writable_dirs) + directories
    return replace(metadata, local_writable_dirs=_canonical_directories(merged))


def update_local_directories(
    artifact: LauncherArtifactMetadata | LauncherMetadata,
    additional_dirs: tuple[str, ...],
    removed_dirs: tuple[str, ...],
) -> tuple[LauncherMetadata, tuple[Path, ...], bool]:
    """Update persisted local directories and report requested entries not stored."""
    additions = _canonical_directories(additional_dirs)
    removals = _canonical_removal_directories(removed_dirs)
    overlap = set(additions).intersection(removals)
    if overlap:
        paths = ", ".join(str(path) for path in sorted(overlap))
        raise LauncherError(f"launcher local directory cannot be both added and removed: {paths}")

    stored = tuple(path.resolve(strict=False) for path in artifact.local_writable_dirs)
    stored_set = set(stored)
    unmatched = tuple(path for path in removals if path not in stored_set)
    retained = tuple(path for path in stored if path not in removals)
    merged = tuple(str(path) for path in retained + additions)
    metadata = build_metadata(
        artifact.agent_id,
        artifact.worktree_dir,
        artifact.preparation_path,
        merged,
        artifact.session.value if artifact.session is not None else None,
        artifact.extensions,
        validate_preparation=False,
    )
    return metadata, unmatched, bool(stored_set.intersection(removals))


def with_git_metadata_access(
    metadata: LauncherMetadata, access: GitMetadataAccess
) -> LauncherMetadata:
    """Persist one explicit Git metadata access policy on a generated launcher."""
    return with_metadata_extension(metadata, "core", "git_metadata_access", access.value)


def with_metadata_extension(
    metadata: LauncherMetadata,
    namespace: str,
    name: str,
    value: MetadataExtensionValue,
) -> LauncherMetadata:
    """Return launcher metadata with one validated optional setting updated."""
    extensions = _copy_extensions(metadata.extensions) or {}
    extensions.setdefault(namespace, {})[name] = value
    return replace(metadata, extensions=_validated_extensions(extensions))


def launcher_git_metadata_access(
    metadata: LauncherMetadata | LauncherArtifactMetadata,
) -> GitMetadataAccess:
    """Return the stored Git metadata policy or the conservative legacy default."""
    if metadata.extensions is None:
        return GitMetadataAccess.WORKTREE
    core = metadata.extensions.get("core")
    if core is None or "git_metadata_access" not in core:
        return GitMetadataAccess.WORKTREE
    value = core["git_metadata_access"]
    if not isinstance(value, str):
        raise LauncherError("launcher metadata has an invalid core.git_metadata_access")
    try:
        return GitMetadataAccess(value)
    except ValueError as error:
        raise LauncherError("launcher metadata has an invalid core.git_metadata_access") from error


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


def _artifact_from_payload(payload: dict[str, object], path: Path) -> LauncherArtifactMetadata:
    expected_keys = {
        "agent_id",
        "format_version",
        "local_writable_dirs",
        "preparation_path",
        "session_id",
        "worktree_dir",
    }
    format_version = payload.get("format_version")
    if (
        not expected_keys.issubset(payload)
        or set(payload).difference(expected_keys | {"extensions", "marker"})
        or not isinstance(format_version, int)
        or isinstance(format_version, bool)
        or format_version != _METADATA_FORMAT_VERSION
    ):
        raise LauncherError(f"unsupported launcher metadata version: {path}")
    agent_value = payload.get("agent_id")
    worktree_value = payload.get("worktree_dir")
    preparation = payload.get("preparation_path")
    session_id = payload.get("session_id")
    directories = payload.get("local_writable_dirs")
    if not isinstance(agent_value, str) or not isinstance(worktree_value, str):
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
        agent_id = AgentId(agent_value)
        session = SessionReference(agent_id, session_id) if session_id is not None else None
        extensions = (
            _validated_extensions(payload["extensions"]) if "extensions" in payload else None
        )
        return LauncherArtifactMetadata(
            format_version=format_version,
            agent_id=agent_id,
            worktree_dir=_artifact_path(worktree_value),
            preparation_path=_artifact_path(preparation) if preparation is not None else None,
            local_writable_dirs=tuple(_artifact_path(directory) for directory in directory_values),
            session=session,
            extensions=extensions,
        )
    except (LauncherError, ValueError) as error:
        raise LauncherError(f"launcher metadata is invalid: {path}: {error}") from error


def _encode_metadata(metadata: LauncherMetadata) -> str:
    payload: dict[str, object] = {
        "agent_id": str(metadata.agent_id),
        "format_version": _METADATA_FORMAT_VERSION,
        "local_writable_dirs": [str(path) for path in metadata.local_writable_dirs],
        "preparation_path": str(metadata.preparation_path)
        if metadata.preparation_path is not None
        else None,
        "session_id": metadata.session.value if metadata.session is not None else None,
        "worktree_dir": str(metadata.worktree_dir),
    }
    if metadata.extensions is not None:
        payload["extensions"] = metadata.extensions
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )


def resolve_preparation_path(
    value: str | Path | None,
    worktree_dir: Path,
    *,
    require_executable: bool,
) -> Path | None:
    """Resolve a helper path from its workspace and optionally validate availability."""
    if value is None:
        return None
    path = _expanded_preparation_path(value)
    if not path.is_absolute():
        path = worktree_dir / path
    path = path.resolve(strict=False)
    if require_executable and (not path.is_file() or not os.access(path, os.X_OK)):
        raise LauncherError(f"preparation path is not an executable file: {path}")
    return path


def _expanded_preparation_path(value: str | Path) -> Path:
    """Expand a preparation argument without resolving it from a worktree."""
    try:
        return Path(value).expanduser()
    except RuntimeError as error:
        raise LauncherError(f"preparation path cannot be expanded: {value}") from error


def _artifact_path(value: str) -> Path:
    """Return one absolute persisted path without requiring it to exist."""
    path = Path(value)
    if not path.is_absolute():
        raise LauncherError("launcher metadata path is not absolute")
    return path


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


def _canonical_removal_directories(values: tuple[str, ...]) -> tuple[Path, ...]:
    """Return unique absolute removal paths without requiring their existence."""
    directories: list[Path] = []
    for value in values:
        raw_path = Path(value)
        try:
            path = raw_path.expanduser()
        except RuntimeError as error:
            raise LauncherError(
                f"launcher local directory removal is not an absolute path: {raw_path}"
            ) from error
        if not path.is_absolute():
            raise LauncherError(f"launcher local directory removal is not an absolute path: {path}")
        resolved = path.resolve(strict=False)
        if resolved not in directories:
            directories.append(resolved)
    return tuple(directories)


def _git_metadata_access_description(
    metadata: LauncherMetadata | LauncherArtifactMetadata,
) -> str:
    access = launcher_git_metadata_access(metadata)
    explicit = metadata.extensions is not None and "git_metadata_access" in metadata.extensions.get(
        "core", {}
    )
    suffix = "" if explicit else " (default)"
    return f"git metadata access: {access.value}{suffix}"


def _validated_extensions(value: object) -> MetadataExtensions:
    if not isinstance(value, dict):
        raise LauncherError("launcher metadata extensions must be an object")
    extensions: MetadataExtensions = {}
    for namespace, raw_settings in cast(dict[object, object], value).items():
        if not isinstance(namespace, str) or not namespace or not isinstance(raw_settings, dict):
            raise LauncherError("launcher metadata extensions must use non-empty object namespaces")
        settings: dict[str, MetadataExtensionValue] = {}
        for name, raw_value in cast(dict[object, object], raw_settings).items():
            if not isinstance(name, str) or not name or not _is_extension_value(raw_value):
                raise LauncherError("launcher metadata extension settings are invalid")
            settings[name] = cast(MetadataExtensionValue, raw_value)
        extensions[namespace] = settings
    core = extensions.get("core")
    if core is not None and "git_metadata_access" in core:
        value = core["git_metadata_access"]
        if not isinstance(value, str):
            raise LauncherError("launcher metadata has an invalid core.git_metadata_access")
        try:
            GitMetadataAccess(value)
        except ValueError as error:
            raise LauncherError(
                "launcher metadata has an invalid core.git_metadata_access"
            ) from error
    return extensions


def _is_extension_value(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _copy_extensions(extensions: MetadataExtensions | None) -> MetadataExtensions | None:
    if extensions is None:
        return None
    return {namespace: dict(settings) for namespace, settings in extensions.items()}


def _atomic_write(path: Path, content: str, mode: int) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    except (OSError, UnicodeError) as error:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        raise LauncherError(f"unable to write {path}: {error}") from error


def _prepare_launcher_target(path_argument: str | Path, *, replace: bool) -> Path:
    """Validate target occupancy and ensure its parent directory exists."""
    path = Path(path_argument).expanduser()
    if (path.exists() or path.is_symlink()) and not replace:
        raise LauncherError(f"launcher path already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise LauncherError(
            f"unable to create launcher directory {path.parent}: {error}"
        ) from error
    return path
