"""Codex-specific runtime behavior kept outside the neutral launcher core."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_agent_launcher._errors import ConfigError, LauncherError
from ai_agent_launcher._models import AgentId
from ai_agent_launcher._runtime import RunContext
from ai_agent_launcher._sessions import CodexSessionCatalog

_CODEX_IDENTIFIER = AgentId("codex")
_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")


@dataclass(frozen=True)
class CodexSettings:
    """Validated values from the `[agents.codex]` TOML table."""

    executable: str
    home: Path | None
    sandbox: str
    model: str | None
    reasoning_effort: str | None
    use_rtk: bool

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> CodexSettings:
        allowed = {"executable", "home", "sandbox", "model", "reasoning_effort", "use_rtk"}
        unexpected = set(values).difference(allowed)
        if unexpected:
            keys = ", ".join(sorted(unexpected))
            raise ConfigError(f"unknown [agents.codex] setting: {keys}")

        executable = (
            _optional_string(values.get("executable"), "agents.codex.executable") or "codex"
        )
        home_value = _optional_string(values.get("home"), "agents.codex.home")
        home = _absolute_path(home_value, "agents.codex.home") if home_value is not None else None
        sandbox = (
            _optional_string(values.get("sandbox"), "agents.codex.sandbox") or "workspace-write"
        )
        if sandbox not in _SANDBOX_MODES:
            choices = ", ".join(_SANDBOX_MODES)
            raise ConfigError(f"agents.codex.sandbox must be one of: {choices}")
        use_rtk = values.get("use_rtk", True)
        if not isinstance(use_rtk, bool):
            raise ConfigError("agents.codex.use_rtk must be a boolean")
        return cls(
            executable=executable,
            home=home,
            sandbox=sandbox,
            model=_optional_string(values.get("model"), "agents.codex.model"),
            reasoning_effort=_optional_string(
                values.get("reasoning_effort"), "agents.codex.reasoning_effort"
            ),
            use_rtk=use_rtk,
        )


@dataclass(frozen=True)
class CodexRunOptions:
    """Codex-only command choices parsed for one invocation."""

    session_id: str | None
    fork_session_id: str | None
    model: str | None
    reasoning_effort: str | None
    sandbox: str | None

    @classmethod
    def from_namespace(cls, arguments: argparse.Namespace) -> CodexRunOptions:
        return cls(
            session_id=arguments.session_id,
            fork_session_id=arguments.fork_session_id,
            model=arguments.model,
            reasoning_effort=arguments.reasoning_effort,
            sandbox=arguments.sandbox,
        )


@dataclass(frozen=True)
class CodexAdapter:
    """Translate neutral run context into the installed Codex CLI."""

    @property
    def identifier(self) -> AgentId:
        """Return the adapter's stable agent identifier."""
        return _CODEX_IDENTIFIER

    def configure_run_parser(self, parser: argparse.ArgumentParser) -> None:
        """Register options that only the Codex adapter understands."""
        group = parser.add_argument_group("Codex options")
        sessions = group.add_mutually_exclusive_group()
        sessions.add_argument("--session-id")
        sessions.add_argument("--fork-session-id")
        group.add_argument("--model")
        group.add_argument("--reasoning-effort")
        group.add_argument("--sandbox", choices=_SANDBOX_MODES)

    def run(
        self,
        context: RunContext,
        settings_values: Mapping[str, object],
        arguments: argparse.Namespace,
    ) -> int:
        """Run Codex with adapter-owned configuration and writable directories."""
        settings = CodexSettings.from_mapping(settings_values)
        options = CodexRunOptions.from_namespace(arguments)
        home = self._home(settings)
        writable_dirs = self._writable_dirs(context)
        command = self._command(settings, options, writable_dirs, context.passthrough_args)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(home)
        environment.setdefault("USE_RTK", "1" if settings.use_rtk else "0")
        environment.setdefault("RUST_LOG", "warn")
        try:
            return subprocess.run(
                command, cwd=context.worktree_dir, env=environment, check=False
            ).returncode
        except FileNotFoundError as error:
            raise LauncherError(f"Codex executable was not found: {settings.executable}") from error
        except OSError as error:
            raise LauncherError(f"unable to start Codex: {error}") from error

    def session_catalog(self, settings_values: Mapping[str, object]) -> CodexSessionCatalog:
        """Return read-only session discovery for the selected Codex home."""
        return CodexSessionCatalog(self._home(CodexSettings.from_mapping(settings_values)))

    def _home(self, settings: CodexSettings) -> Path:
        environment_home = os.environ.get("CODEX_HOME")
        if environment_home:
            return _absolute_path(environment_home, "CODEX_HOME")
        if settings.home is not None:
            return settings.home
        return Path.home() / ".codex"

    def _writable_dirs(self, context: RunContext) -> tuple[Path, ...]:
        directories: list[Path] = []
        for configured_dir in context.configured_writable_dirs:
            _append_unique(
                directories, _existing_directory(configured_dir, "configured writable directory")
            )
        for requested_dir in context.requested_writable_dirs:
            _append_unique(directories, _existing_directory(requested_dir, "--add-dir"))

        context_dir = context.worktree_dir / ".context"
        if context_dir.is_dir():
            _append_unique(directories, context_dir.resolve())
        _append_unique(directories, self._git_dir(context.worktree_dir))
        for cache_dir in self._cache_dirs(context.worktree_dir):
            _append_unique(directories, cache_dir)
        return tuple(directories)

    def _git_dir(self, worktree_dir: Path) -> Path:
        try:
            result = subprocess.run(
                ["git", "-C", str(worktree_dir), "rev-parse", "--git-dir"],
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            details = error.stderr.strip() or "unable to determine the Git directory"
            raise LauncherError(details) from error
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = worktree_dir / git_dir
        return git_dir.resolve()

    def _cache_dirs(self, worktree_dir: Path) -> tuple[Path, ...]:
        directories: list[Path] = []
        go = shutil.which("go")
        if go is not None:
            go_cache = self._go_environment(go, "GOCACHE", worktree_dir)
            if go_cache != "off":
                _append_unique(directories, _create_directory(go_cache, "Go build cache"))
            go_module_cache = self._go_environment(go, "GOMODCACHE", worktree_dir)
            _append_unique(directories, _create_directory(go_module_cache, "Go module cache"))
        if shutil.which("golangci-lint") is not None:
            cache_root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
            golangci_cache = os.environ.get("GOLANGCI_LINT_CACHE") or str(
                Path(cache_root).expanduser() / "golangci-lint"
            )
            _append_unique(directories, _create_directory(golangci_cache, "Golangci cache"))
        return tuple(directories)

    def _go_environment(self, executable: str, variable: str, worktree_dir: Path) -> str:
        try:
            result = subprocess.run(
                [executable, "env", variable],
                capture_output=True,
                check=True,
                cwd=worktree_dir,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            details = error.stderr.strip() or f"unable to determine {variable}"
            raise LauncherError(details) from error
        value = result.stdout.strip()
        if not value:
            raise LauncherError(f"Go returned an empty {variable}")
        return value

    def _command(
        self,
        settings: CodexSettings,
        options: CodexRunOptions,
        writable_dirs: tuple[Path, ...],
        passthrough_args: tuple[str, ...],
    ) -> list[str]:
        sandbox = options.sandbox or settings.sandbox
        model = options.model or settings.model
        reasoning_effort = options.reasoning_effort or settings.reasoning_effort
        common_args = ["--sandbox", sandbox]
        if model is not None:
            common_args.extend(("--model", model))
        if reasoning_effort is not None:
            common_args.extend(
                ("--config", f"model_reasoning_effort={json.dumps(reasoning_effort)}")
            )
        for writable_dir in writable_dirs:
            common_args.extend(("--add-dir", str(writable_dir)))

        command = [settings.executable]
        if options.fork_session_id is not None:
            command.extend(("fork", *common_args, options.fork_session_id))
        elif options.session_id is not None:
            command.extend(("resume", *common_args, options.session_id))
        else:
            command.extend(common_args)
        command.extend(passthrough_args)
        return command


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label} must be a non-empty string")
    return value


def _absolute_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{label} must be an absolute path")
    return path


def _existing_directory(value: str, label: str) -> Path:
    path = _absolute_path(value, label)
    if not path.is_dir():
        raise LauncherError(f"{label} is not an existing directory: {path}")
    return path.resolve()


def _create_directory(value: str, label: str) -> Path:
    path = _absolute_path(value, label)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise LauncherError(f"unable to create {label}: {path}: {error}") from error
    if not path.is_dir():
        raise LauncherError(f"{label} is not a directory: {path}")
    return path.resolve()


def _append_unique(directories: list[Path], candidate: Path) -> None:
    if candidate not in directories:
        directories.append(candidate)
