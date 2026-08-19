"""Explicit Codex migration from legacy Bash launcher artifacts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import ConfigError, LauncherError
from ai_agent_launcher._launchers import (
    LauncherMetadata,
    atomic_text_write,
    build_metadata,
    launcher_mode,
    write_launcher,
)
from ai_agent_launcher._models import AgentId

_KNOWN_CONFIG_VARIABLES = (
    "CODEX_HOME",
    "CODEX_LAUNCHER_ADD_DIRS",
    "CODEX_LAUNCHER_MODEL",
    "CODEX_LAUNCHER_REASONING_EFFORT",
    "CODEX_LAUNCHER_SANDBOX",
    "CODEX_LAUNCHER_USE_RTK",
)
_ASSIGNMENT = re.compile(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")


def migrate_legacy_config(
    source_argument: str | Path,
    target_argument: str | Path,
    *,
    trusted: bool,
    replace: bool,
) -> tuple[str, ...]:
    """Map a trusted legacy Bash fragment to the supported launcher TOML schema."""
    if not trusted:
        raise LauncherError("legacy shell configuration requires --trust-legacy-shell-config")
    source = Path(source_argument).expanduser()
    target = Path(target_argument).expanduser()
    if not source.is_file():
        raise LauncherError(f"legacy configuration is not a file: {source}")
    if target.exists() and not replace:
        raise LauncherError(f"configuration path already exists: {target}; use --replace")
    values = _source_legacy_config(source)
    document = _toml_document(values)
    mode = launcher_mode(target) if target.exists() else 0o600
    atomic_text_write(target, document, mode)
    source_text = source.read_text(encoding="utf-8")
    unknown = tuple(
        sorted(set(_ASSIGNMENT.findall(source_text)).difference(_KNOWN_CONFIG_VARIABLES))
    )
    return unknown


def read_legacy_launcher(
    source_argument: str | Path,
    *,
    agent_id: AgentId,
    marker: str,
    preparation_path: str | Path,
) -> LauncherMetadata:
    """Read only known legacy generated-launcher fields after exact marker verification."""
    source = Path(source_argument).expanduser()
    try:
        content = source.read_text(encoding="utf-8")
    except OSError as error:
        raise LauncherError(f"unable to read legacy launcher {source}: {error}") from error
    if marker not in content.splitlines():
        raise LauncherError(f"legacy launcher is missing the expected marker: {source}")
    worktree = _legacy_field(content, "worktree_dir")
    session_id = _legacy_field(content, "default_session_id", required=False)
    directories = _legacy_extra_dirs(content)
    return build_metadata(
        agent_id, worktree, marker, preparation_path, directories, session_id or None
    )


def migrate_legacy_launcher(
    source_argument: str | Path,
    target_argument: str | Path,
    *,
    agent_id: AgentId,
    marker: str,
    preparation_path: str | Path,
    replace: bool,
) -> Path:
    """Render a versioned target while preserving the legacy launcher's mode and marker."""
    source = Path(source_argument).expanduser()
    target = Path(target_argument).expanduser()
    if target.exists() and not replace:
        raise LauncherError(f"launcher path already exists: {target}; use --replace")
    if source.resolve() == target.resolve() and not replace:
        raise LauncherError("in-place launcher migration requires --replace")
    metadata = read_legacy_launcher(
        source, agent_id=agent_id, marker=marker, preparation_path=preparation_path
    )
    return write_launcher(target, metadata, replace=replace, mode=launcher_mode(source))


def _source_legacy_config(source: Path) -> dict[str, object]:
    script = """
set -eu
source "$1"
printf '%s\\0%s\\0' CODEX_HOME "${CODEX_HOME-}"
printf '%s\\0%s\\0' CODEX_LAUNCHER_MODEL "${CODEX_LAUNCHER_MODEL-}"
printf '%s\\0%s\\0' CODEX_LAUNCHER_REASONING_EFFORT "${CODEX_LAUNCHER_REASONING_EFFORT-}"
printf '%s\\0%s\\0' CODEX_LAUNCHER_SANDBOX "${CODEX_LAUNCHER_SANDBOX-}"
printf '%s\\0%s\\0' CODEX_LAUNCHER_USE_RTK "${CODEX_LAUNCHER_USE_RTK-}"
printf '%s\\0' CODEX_LAUNCHER_ADD_DIRS
for value in "${CODEX_LAUNCHER_ADD_DIRS[@]-}"; do printf '%s\\0' "$value"; done
printf '\\0'
"""
    try:
        result = subprocess.run(
            ["bash", "-c", script, "bash", str(source)],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as error:
        raise LauncherError("bash is required to migrate a trusted legacy configuration") from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.decode("utf-8", errors="replace").strip()
        raise LauncherError(f"unable to source legacy configuration: {details}") from error
    fields = result.stdout.split(b"\0")
    values: dict[str, object] = {}
    index = 0
    while index < len(fields) - 1:
        name = fields[index].decode("utf-8")
        index += 1
        if name == "CODEX_LAUNCHER_ADD_DIRS":
            directories: list[str] = []
            while index < len(fields) and fields[index]:
                directories.append(fields[index].decode("utf-8"))
                index += 1
            index += 1
            values[name] = directories
            continue
        values[name] = fields[index].decode("utf-8")
        index += 1
    return values


def _toml_document(values: dict[str, object]) -> str:
    raw_dirs = values["CODEX_LAUNCHER_ADD_DIRS"]
    if not isinstance(raw_dirs, list):
        raise ConfigError("legacy CODEX_LAUNCHER_ADD_DIRS must be a Bash array of strings")
    directories: list[str] = []
    for value in cast(list[object], raw_dirs):
        if not isinstance(value, str):
            raise ConfigError("legacy CODEX_LAUNCHER_ADD_DIRS must be a Bash array of strings")
        directories.append(value)
    settings: list[tuple[str, str]] = []
    mapping = {
        "CODEX_HOME": "home",
        "CODEX_LAUNCHER_MODEL": "model",
        "CODEX_LAUNCHER_REASONING_EFFORT": "reasoning_effort",
        "CODEX_LAUNCHER_SANDBOX": "sandbox",
    }
    for legacy_name, toml_name in mapping.items():
        value = values.get(legacy_name)
        if isinstance(value, str) and value:
            settings.append((toml_name, _toml_string(value)))
    rtk = values.get("CODEX_LAUNCHER_USE_RTK")
    if isinstance(rtk, str) and rtk:
        if rtk in {"1", "true"}:
            settings.append(("use_rtk", "true"))
        elif rtk in {"0", "false"}:
            settings.append(("use_rtk", "false"))
        else:
            raise ConfigError("legacy CODEX_LAUNCHER_USE_RTK must be 0, 1, true, or false")
    lines = [
        "[core]",
        f"writable_dirs = [{', '.join(_toml_string(value) for value in directories)}]",
    ]
    if settings:
        lines.extend(("", "[agents.codex]"))
        lines.extend(f"{name} = {value}" for name, value in settings)
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    import json

    return json.dumps(value)


def _legacy_field(content: str, field: str, *, required: bool = True) -> str:
    encoded_match = re.search(
        rf"(?m)^# codex-launcher-{re.escape(field)}-hex: ([0-9A-Fa-f]*)$", content
    )
    if encoded_match is not None:
        try:
            return bytes.fromhex(encoded_match.group(1)).decode("utf-8")
        except ValueError as error:
            raise LauncherError(f"legacy launcher has invalid {field} metadata") from error
    assignment = re.search(rf"(?m)^{re.escape(field)}=(.*)$", content)
    if assignment is not None:
        value = assignment.group(1).strip()
        if value in {"''", '""'}:
            return ""
        if re.fullmatch(r"[A-Za-z0-9_./:@+ -]+", value):
            return value
        raise LauncherError(f"legacy launcher has an unsupported {field} value")
    if required:
        raise LauncherError(f"legacy launcher is missing {field}")
    return ""


def _legacy_extra_dirs(content: str) -> tuple[str, ...]:
    values: list[str] = []
    for encoded in re.findall(r"(?m)^# codex-launcher-extra-add-dir-hex: ([0-9A-Fa-f]*)$", content):
        try:
            value = bytes.fromhex(encoded).decode("utf-8")
        except ValueError as error:
            raise LauncherError("legacy launcher has invalid local directory metadata") from error
        if value not in values:
            values.append(value)
    return tuple(values)
