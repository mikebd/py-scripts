"""Claude Code-specific runtime behavior kept outside the neutral launcher core."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_agent_launcher._adapters import AgentSessionMetadata, WritableDirectoryReport
from ai_agent_launcher._claude_sessions import ClaudeSessionCatalog
from ai_agent_launcher._errors import ConfigError, LauncherError
from ai_agent_launcher._models import AgentId, GitMetadataAccess, SessionReference
from ai_agent_launcher._runtime import RunContext

_CLAUDE_IDENTIFIER = AgentId("claude")
_PERMISSION_MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ClaudeSettings:
    """Validated values from the `[agents.claude]` TOML table."""

    executable: str
    home: Path | None
    permission_mode: str
    model: str | None
    effort: str | None

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> ClaudeSettings:
        allowed = {"executable", "home", "permission_mode", "model", "effort"}
        unexpected = set(values).difference(allowed)
        if unexpected:
            keys = ", ".join(sorted(unexpected))
            raise ConfigError(f"unknown [agents.claude] setting: {keys}")

        executable = (
            _optional_string(values.get("executable"), "agents.claude.executable") or "claude"
        )
        home_value = _optional_string(values.get("home"), "agents.claude.home")
        home = _absolute_path(home_value, "agents.claude.home") if home_value is not None else None
        permission_mode = (
            _optional_string(values.get("permission_mode"), "agents.claude.permission_mode")
            or "auto"
        )
        if permission_mode not in _PERMISSION_MODES:
            choices = ", ".join(_PERMISSION_MODES)
            raise ConfigError(f"agents.claude.permission_mode must be one of: {choices}")
        effort = _optional_string(values.get("effort"), "agents.claude.effort")
        if effort is not None and effort not in _EFFORT_LEVELS:
            choices = ", ".join(_EFFORT_LEVELS)
            raise ConfigError(f"agents.claude.effort must be one of: {choices}")
        return cls(
            executable=executable,
            home=home,
            permission_mode=permission_mode,
            model=_optional_string(values.get("model"), "agents.claude.model"),
            effort=effort,
        )


@dataclass(frozen=True)
class ClaudeRunOptions:
    """Claude-only command choices parsed for one invocation."""

    session_id: str | None
    fork_session_id: str | None
    model: str | None
    permission_mode: str | None
    effort: str | None

    @classmethod
    def from_namespace(cls, arguments: argparse.Namespace) -> ClaudeRunOptions:
        return cls(
            session_id=arguments.session_id,
            fork_session_id=arguments.fork_session_id,
            model=arguments.model,
            permission_mode=arguments.permission_mode,
            effort=arguments.effort,
        )


@dataclass(frozen=True)
class ClaudeAdapter:
    """Translate neutral run context into the installed Claude Code CLI."""

    @property
    def identifier(self) -> AgentId:
        """Return the adapter's stable agent identifier."""
        return _CLAUDE_IDENTIFIER

    @property
    def launcher_sandbox_modes(self) -> tuple[str, ...]:
        """Return Claude permission modes accepted for persisted launcher overrides."""
        return _PERMISSION_MODES

    def validate_launcher_sandbox_mode(self, mode: str) -> None:
        """Reject a permission mode unavailable in the installed Claude adapter."""
        if mode not in _PERMISSION_MODES:
            choices = ", ".join(_PERMISSION_MODES)
            raise LauncherError(f"Claude permission mode must be one of: {choices}")

    def configure_run_parser(self, parser: argparse.ArgumentParser) -> None:
        """Register options that only the Claude adapter understands."""
        group = parser.add_argument_group("Claude options")
        sessions = group.add_mutually_exclusive_group()
        sessions.add_argument("--session-id")
        sessions.add_argument("--fork-session-id")
        group.add_argument("--model")
        group.add_argument("--permission-mode", choices=_PERMISSION_MODES)
        group.add_argument("--effort", choices=_EFFORT_LEVELS)

    def run(
        self,
        context: RunContext,
        settings_values: Mapping[str, object],
        arguments: argparse.Namespace,
    ) -> int:
        """Run Claude Code with adapter-owned configuration and writable directories."""
        settings = ClaudeSettings.from_mapping(settings_values)
        options = ClaudeRunOptions.from_namespace(arguments)
        home = self._home(settings)
        writable_dirs = self._writable_dirs(context)
        command = self._command(settings, options, writable_dirs, context.passthrough_args)
        environment = os.environ.copy()
        environment["CLAUDE_CONFIG_DIR"] = str(home)
        try:
            return subprocess.run(
                command, cwd=context.worktree_dir, env=environment, check=False
            ).returncode
        except FileNotFoundError as error:
            message = f"Claude executable was not found: {settings.executable}"
            raise LauncherError(message) from error
        except OSError as error:
            raise LauncherError(f"unable to start Claude: {error}") from error

    def run_launcher(
        self,
        context: RunContext,
        settings_values: Mapping[str, object],
        session: SessionReference | None,
        passthrough_args: tuple[str, ...],
    ) -> int:
        """Translate generic generated-launcher metadata into Claude run options."""
        if session is not None and session.agent_id != self.identifier:
            raise LauncherError(f"Claude cannot run a {session.agent_id} session")
        arguments = argparse.Namespace(
            session_id=session.value if session is not None else None,
            fork_session_id=None,
            model=None,
            permission_mode=self._launcher_sandbox_mode(context),
            effort=None,
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
        """Return the optional persisted Claude permission-mode override from launcher metadata."""
        extensions = context.launcher_extensions
        if extensions is None:
            return None
        settings = extensions.get(str(self.identifier))
        if settings is None or "sandbox" not in settings:
            return None
        mode = settings["sandbox"]
        if not isinstance(mode, str):
            raise LauncherError("launcher metadata has an invalid claude.sandbox")
        try:
            self.validate_launcher_sandbox_mode(mode)
        except LauncherError as error:
            raise LauncherError("launcher metadata has an invalid claude.sandbox") from error
        return mode

    def resolve_writable_dirs(
        self,
        context: RunContext,
        _settings_values: Mapping[str, object],
    ) -> WritableDirectoryReport:
        """Best-effort resolve Claude writable directories without creating cache paths."""
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
        return WritableDirectoryReport(tuple(directories), tuple(notes))

    def session_catalog(self, settings_values: Mapping[str, object]) -> ClaudeSessionCatalog:
        """Return read-only session discovery for the selected Claude home."""
        return ClaudeSessionCatalog(self._home(ClaudeSettings.from_mapping(settings_values)))

    def find_session(
        self, settings_values: Mapping[str, object], session: SessionReference
    ) -> AgentSessionMetadata:
        """Find one Claude session and project it into neutral lifecycle metadata."""
        if session.agent_id != self.identifier:
            raise LauncherError(f"Claude cannot resolve a {session.agent_id} session")
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
        """Fork one Claude session and require exactly one new matching record."""
        if parent.agent_id != self.identifier:
            raise LauncherError(f"Claude cannot fork a {parent.agent_id} session")
        catalog = self.session_catalog(settings_values)
        before = {record.source_file for record in catalog.records()}
        arguments = argparse.Namespace(
            session_id=None,
            fork_session_id=parent.value,
            model=None,
            permission_mode=None,
            effort=None,
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
            raise LauncherError(f"Claude fork exited with status {exit_status}")
        candidates = [
            record
            for record in catalog.records()
            if record.source_file not in before
            and record.forked_from_identifier == parent.value
            and record.working_directory.resolve() == context.worktree_dir
        ]
        if len(candidates) != 1:
            raise LauncherError(f"expected one new forked Claude session, found {len(candidates)}")
        return SessionReference(self.identifier, candidates[0].identifier)

    def _home(self, settings: ClaudeSettings) -> Path:
        environment_home = os.environ.get("CLAUDE_CONFIG_DIR")
        if environment_home:
            return _absolute_path(environment_home, "CLAUDE_CONFIG_DIR")
        if settings.home is not None:
            return settings.home
        return Path.home() / ".claude"

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

    def _command(
        self,
        settings: ClaudeSettings,
        options: ClaudeRunOptions,
        writable_dirs: tuple[Path, ...],
        passthrough_args: tuple[str, ...],
    ) -> list[str]:
        permission_mode = options.permission_mode or settings.permission_mode
        model = options.model or settings.model
        effort = options.effort or settings.effort
        command = [settings.executable, "--permission-mode", permission_mode]
        if model is not None:
            command.extend(("--model", model))
        if effort is not None:
            command.extend(("--effort", effort))
        for writable_dir in writable_dirs:
            command.extend(("--add-dir", str(writable_dir)))

        if options.fork_session_id is not None:
            command.extend(("--resume", options.fork_session_id, "--fork-session"))
        elif options.session_id is not None:
            command.extend(("--resume", options.session_id))
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
