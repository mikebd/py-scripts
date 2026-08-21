"""TOML configuration loading for the neutral launcher core."""

import os
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import ConfigError
from ai_agent_launcher._models import AgentId


@dataclass(frozen=True)
class CoreConfig:
    """Configuration shared by every supported agent."""

    writable_dirs: tuple[str, ...]
    launcher_directory: Path | None


@dataclass(frozen=True)
class LauncherConfig:
    """Validated launcher configuration split by neutral and agent-specific settings."""

    core: CoreConfig
    agent_settings: Mapping[AgentId, Mapping[str, object]]


def default_config_path() -> Path:
    """Return the conventional XDG configuration location."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    return config_home / "ai-agent-launcher" / "config.toml"


def load_config(
    explicit_path: Path | None,
    available_agents: Iterable[AgentId],
) -> LauncherConfig:
    """Load one TOML file or return defaults when the default file is absent."""
    path = default_config_path() if explicit_path is None else explicit_path.expanduser()
    if not path.exists():
        if explicit_path is None:
            return LauncherConfig(
                core=CoreConfig(writable_dirs=(), launcher_directory=None), agent_settings={}
            )
        raise ConfigError(f"configuration file does not exist: {path}")
    if not path.is_file():
        raise ConfigError(f"configuration path is not a file: {path}")

    try:
        with path.open("rb") as config_file:
            document = cast(dict[str, object], tomllib.load(config_file))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"unable to read configuration file {path}: {error}") from error

    unexpected_root_keys = set(document).difference({"core", "agents"})
    if unexpected_root_keys:
        keys = ", ".join(sorted(unexpected_root_keys))
        raise ConfigError(f"unknown configuration table or key: {keys}")

    core = _parse_core(document.get("core", {}))
    agent_settings = _parse_agent_settings(document.get("agents", {}), available_agents)
    return LauncherConfig(core=core, agent_settings=agent_settings)


def _parse_core(value: object) -> CoreConfig:
    table = _require_table(value, "[core]")
    unexpected_keys = set(table).difference({"writable_dirs", "launcher_directory"})
    if unexpected_keys:
        keys = ", ".join(sorted(unexpected_keys))
        raise ConfigError(f"unknown [core] setting: {keys}")

    raw_writable_dirs = table.get("writable_dirs", [])
    if not isinstance(raw_writable_dirs, list):
        raise ConfigError("core.writable_dirs must be an array of strings")
    writable_dirs: list[str] = []
    for item in cast(list[object], raw_writable_dirs):
        if not isinstance(item, str):
            raise ConfigError("core.writable_dirs must be an array of strings")
        writable_dirs.append(item)
    launcher_directory = table.get("launcher_directory")
    if launcher_directory is not None:
        if not isinstance(launcher_directory, str) or not launcher_directory:
            raise ConfigError("core.launcher_directory must be a non-empty absolute path")
        candidate = Path(launcher_directory).expanduser()
        if not candidate.is_absolute():
            raise ConfigError("core.launcher_directory must be a non-empty absolute path")
        launcher_directory_path: Path | None = candidate.resolve()
    else:
        launcher_directory_path = None
    return CoreConfig(
        writable_dirs=tuple(writable_dirs),
        launcher_directory=launcher_directory_path,
    )


def _parse_agent_settings(
    value: object,
    available_agents: Iterable[AgentId],
) -> Mapping[AgentId, Mapping[str, object]]:
    table = _require_table(value, "[agents]")
    available = set(available_agents)
    settings: dict[AgentId, Mapping[str, object]] = {}
    for name, agent_value in table.items():
        try:
            identifier = AgentId(name)
        except ValueError as error:
            raise ConfigError(f"invalid agent configuration table: agents.{name}") from error
        if identifier not in available:
            raise ConfigError(f"configuration names unsupported agent: {identifier}")
        settings[identifier] = _require_table(agent_value, f"[agents.{identifier}]")
    return settings


def _require_table(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a TOML table")
    table: dict[str, object] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if not isinstance(key, str):
            raise ConfigError(f"{label} must be a TOML table")
        table[key] = item
    return table
