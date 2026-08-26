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

from ai_agent_launcher._adapters import AgentSessionMetadata, WritableDirectoryReport
from ai_agent_launcher._errors import ConfigError, LauncherError
from ai_agent_launcher._models import AgentId, GitMetadataAccess, SessionReference
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

    @property
    def launcher_sandbox_modes(self) -> tuple[str, ...]:
        """Return Codex modes accepted for persisted launcher overrides."""
        return _SANDBOX_MODES

    def validate_launcher_sandbox_mode(self, mode: str) -> None:
        """Reject a sandbox mode unavailable in the installed Codex adapter."""
        if mode not in _SANDBOX_MODES:
            choices = ", ".join(_SANDBOX_MODES)
            raise LauncherError(f"Codex sandbox mode must be one of: {choices}")

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

    def run_launcher(
        self,
        context: RunContext,
        settings_values: Mapping[str, object],
        session: SessionReference | None,
        passthrough_args: tuple[str, ...],
    ) -> int:
        """Translate generic generated-launcher metadata into Codex run options."""
        if session is not None and session.agent_id != self.identifier:
            raise LauncherError(f"Codex cannot run a {session.agent_id} session")
        arguments = argparse.Namespace(
            session_id=session.value if session is not None else None,
            fork_session_id=None,
            model=None,
            reasoning_effort=None,
            sandbox=self._launcher_sandbox_mode(context),
        )
        launcher_context = RunContext(
            worktree_dir=context.worktree_dir,
            configured_writable_dirs=context.configured_writable_dirs,
            requested_writable_dirs=context.requested_writable_dirs,
            passthrough_args=passthrough_args,
            git_metadata_access=context.git_metadata_access,
        )
        return self.run(launcher_context, settings_values, arguments)

    def _launcher_sandbox_mode(self, context: RunContext) -> str | None:
        """Return the optional persisted Codex sandbox override from launcher metadata."""
        extensions = context.launcher_extensions
        if extensions is None:
            return None
        settings = extensions.get(str(self.identifier))
        if settings is None or "sandbox" not in settings:
            return None
        sandbox = settings["sandbox"]
        if not isinstance(sandbox, str):
            raise LauncherError("launcher metadata has an invalid codex.sandbox")
        try:
            self.validate_launcher_sandbox_mode(sandbox)
        except LauncherError as error:
            raise LauncherError("launcher metadata has an invalid codex.sandbox") from error
        return sandbox

    def resolve_writable_dirs(
        self,
        context: RunContext,
        _settings_values: Mapping[str, object],
    ) -> WritableDirectoryReport:
        """Best-effort resolve Codex writable directories without creating cache paths."""
        directories: list[Path] = []
        notes: list[str] = []
        configured_dirs: list[Path] = []
        for configured_dir in context.configured_writable_dirs:
            _append_existing_or_note(
                configured_dirs, notes, configured_dir, "configured writable directory"
            )
        try:
            git_dirs = self._git_dirs(context)
        except LauncherError as error:
            git_dirs = ()
            notes.append(str(error))
        for configured_dir in configured_dirs:
            if _contains_automatic_git_directory(configured_dir, git_dirs):
                notes.append(
                    "configured writable directory contains automatic Git metadata and is omitted: "
                    f"{configured_dir}"
                )
            else:
                _append_unique(directories, configured_dir)
        for requested_dir in context.requested_writable_dirs:
            _append_existing_or_note(directories, notes, requested_dir, "--add-dir")

        context_dir = context.worktree_dir / ".context"
        if context_dir.is_dir():
            _append_unique(directories, context_dir.resolve())
        for git_dir in git_dirs:
            _append_unique(directories, git_dir)
        cache_dirs, cache_notes = self._described_cache_dirs(context.worktree_dir)
        for cache_dir in cache_dirs:
            _append_unique(directories, cache_dir)
        notes.extend(cache_notes)
        return WritableDirectoryReport(tuple(directories), tuple(notes))

    def session_catalog(self, settings_values: Mapping[str, object]) -> CodexSessionCatalog:
        """Return read-only session discovery for the selected Codex home."""
        return CodexSessionCatalog(self._home(CodexSettings.from_mapping(settings_values)))

    def find_session(
        self, settings_values: Mapping[str, object], session: SessionReference
    ) -> AgentSessionMetadata:
        """Find one Codex session and project it into neutral lifecycle metadata."""
        if session.agent_id != self.identifier:
            raise LauncherError(f"Codex cannot resolve a {session.agent_id} session")
        record = self.session_catalog(settings_values).find_unique(session.value)
        parent = (
            SessionReference(self.identifier, record.forked_from_identifier)
            if record.forked_from_identifier is not None
            else None
        )
        return AgentSessionMetadata(
            session=session,
            working_directory=record.working_directory.resolve(),
            forked_from=parent,
        )

    def fork_session(
        self,
        context: RunContext,
        settings_values: Mapping[str, object],
        parent: SessionReference,
        passthrough_args: tuple[str, ...],
    ) -> SessionReference:
        """Fork one Codex session and require exactly one new matching record."""
        if parent.agent_id != self.identifier:
            raise LauncherError(f"Codex cannot fork a {parent.agent_id} session")
        catalog = self.session_catalog(settings_values)
        before = {record.source_file for record in catalog.records()}
        arguments = argparse.Namespace(
            session_id=None,
            fork_session_id=parent.value,
            model=None,
            reasoning_effort=None,
            sandbox=None,
        )
        fork_context = RunContext(
            worktree_dir=context.worktree_dir,
            configured_writable_dirs=context.configured_writable_dirs,
            requested_writable_dirs=context.requested_writable_dirs,
            passthrough_args=passthrough_args,
            git_metadata_access=context.git_metadata_access,
        )
        exit_status = self.run(fork_context, settings_values, arguments)
        if exit_status != 0:
            raise LauncherError(f"Codex fork exited with status {exit_status}")
        candidates = [
            record
            for record in catalog.records()
            if record.source_file not in before
            and record.forked_from_identifier == parent.value
            and record.working_directory.resolve() == context.worktree_dir
        ]
        if len(candidates) != 1:
            raise LauncherError(f"expected one new forked Codex session, found {len(candidates)}")
        return SessionReference(self.identifier, candidates[0].identifier)

    def _home(self, settings: CodexSettings) -> Path:
        environment_home = os.environ.get("CODEX_HOME")
        if environment_home:
            return _absolute_path(environment_home, "CODEX_HOME")
        if settings.home is not None:
            return settings.home
        return Path.home() / ".codex"

    def _writable_dirs(self, context: RunContext) -> tuple[Path, ...]:
        directories: list[Path] = []
        git_dirs = self._git_dirs(context)
        for configured_dir in context.configured_writable_dirs:
            directory = _existing_directory(configured_dir, "configured writable directory")
            if not _contains_automatic_git_directory(directory, git_dirs):
                _append_unique(directories, directory)
        for requested_dir in context.requested_writable_dirs:
            _append_unique(directories, _existing_directory(requested_dir, "--add-dir"))

        context_dir = context.worktree_dir / ".context"
        if context_dir.is_dir():
            _append_unique(directories, context_dir.resolve())
        for git_dir in git_dirs:
            _append_unique(directories, git_dir)
        for cache_dir in self._cache_dirs(context.worktree_dir):
            _append_unique(directories, cache_dir)
        return tuple(directories)

    def _git_dirs(self, context: RunContext) -> tuple[Path, ...]:
        directories = [self._git_path(context.worktree_dir, "--git-dir", "Git directory")]
        if context.git_metadata_access is GitMetadataAccess.SHARED:
            directories.append(
                self._git_path(context.worktree_dir, "--git-common-dir", "Git common directory")
            )
        return tuple(dict.fromkeys(directories))

    def _git_path(self, worktree_dir: Path, argument: str, label: str) -> Path:
        try:
            result = subprocess.run(
                ["git", "-C", str(worktree_dir), "rev-parse", argument],
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            details = error.stderr.strip() or f"unable to determine the {label}"
            raise LauncherError(details) from error
        except OSError as error:
            raise LauncherError(f"unable to determine the {label}: {error}") from error
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
            if go_module_cache != "off":
                _append_unique(directories, _create_directory(go_module_cache, "Go module cache"))
        if shutil.which("golangci-lint") is not None:
            cache_root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
            golangci_cache = os.environ.get("GOLANGCI_LINT_CACHE") or str(
                Path(cache_root).expanduser() / "golangci-lint"
            )
            _append_unique(directories, _create_directory(golangci_cache, "Golangci cache"))
        return tuple(directories)

    def _described_cache_dirs(self, worktree_dir: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        directories: list[Path] = []
        notes: list[str] = []
        go = shutil.which("go")
        if go is not None:
            for variable, label in (
                ("GOCACHE", "Go build cache"),
                ("GOMODCACHE", "Go module cache"),
            ):
                try:
                    value = self._go_environment(go, variable, worktree_dir)
                    if value != "off":
                        _append_unique(directories, _cache_path(value, label))
                except LauncherError as error:
                    notes.append(str(error))
        if shutil.which("golangci-lint") is not None:
            cache_root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
            golangci_cache = os.environ.get("GOLANGCI_LINT_CACHE") or str(
                Path(cache_root).expanduser() / "golangci-lint"
            )
            try:
                _append_unique(directories, _cache_path(golangci_cache, "Golangci cache"))
            except LauncherError as error:
                notes.append(str(error))
        return tuple(directories), tuple(notes)

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
        except OSError as error:
            raise LauncherError(f"unable to determine {variable}: {error}") from error
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


def _cache_path(value: str, label: str) -> Path:
    """Resolve a cache location without creating it for inspection."""
    return _absolute_path(value, label).resolve()


def _append_existing_or_note(
    directories: list[Path], notes: list[str], value: str, label: str
) -> None:
    try:
        _append_unique(directories, _existing_directory(value, label))
    except LauncherError as error:
        notes.append(str(error))


def _append_unique(directories: list[Path], candidate: Path) -> None:
    if candidate not in directories:
        directories.append(candidate)


def _contains_automatic_git_directory(directory: Path, git_dirs: tuple[Path, ...]) -> bool:
    """Report whether a configured root would overlap an automatic Git metadata root."""
    return any(directory != git_dir and git_dir.is_relative_to(directory) for git_dir in git_dirs)
