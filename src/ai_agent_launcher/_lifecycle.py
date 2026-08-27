"""Agent-neutral generated-launcher lifecycle orchestration."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from ai_agent_launcher._adapters import (
    LauncherSandboxAdapter,
    RuntimeAgentAdapter,
    SessionLifecycleAdapter,
)
from ai_agent_launcher._config import LauncherConfig
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import (
    LauncherMetadata,
    build_metadata,
    launcher_git_metadata_access,
    launcher_mode,
    preflight_launcher_target,
    read_launcher,
    read_launcher_artifact,
    replace_session,
    resolve_preparation_path,
    update_local_directories,
    with_git_metadata_access,
    with_metadata_extension,
    write_launcher,
)
from ai_agent_launcher._models import AgentId, GitMetadataAccess, SessionReference
from ai_agent_launcher._registry import AgentRegistry
from ai_agent_launcher._runtime import RunContext


class LauncherLifecycle:
    """Render, execute, and update versioned launchers through registered adapters."""

    def __init__(self, registry: AgentRegistry, config: LauncherConfig) -> None:
        self._registry = registry
        self._config = config

    def create(
        self,
        agent_id: AgentId,
        launcher: Path,
        worktree_dir: Path,
        preparation_path: Path | None,
        local_writable_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
        sandbox_mode: str | None = None,
        *,
        validate_preparation: bool = True,
    ) -> Path:
        """Create an initially unpinned launcher for an existing worktree."""
        self.validate_creation(agent_id, sandbox_mode)
        metadata = build_metadata(
            agent_id,
            worktree_dir,
            preparation_path,
            local_writable_dirs,
            validate_preparation=validate_preparation,
        )
        access = git_metadata_access or self._config.core.default_git_metadata_access
        metadata = with_git_metadata_access(metadata, access)
        return write_launcher(launcher, self._with_sandbox_mode(metadata, sandbox_mode))

    def validate_creation(self, agent_id: AgentId, sandbox_mode: str | None) -> None:
        """Validate adapter capabilities required before creating launcher resources."""
        self._runtime_adapter(agent_id)
        if sandbox_mode is not None:
            self._sandbox_adapter(agent_id).validate_launcher_sandbox_mode(sandbox_mode)

    def run(self, launcher: Path, passthrough_args: tuple[str, ...]) -> int:
        """Run a rendered launcher through its selected runtime adapter."""
        metadata = read_launcher(launcher)
        self._run_preparation(metadata)
        adapter = self._runtime_adapter(metadata.agent_id)
        return adapter.run_launcher(
            self._context(metadata, passthrough_args),
            self._settings(metadata.agent_id),
            metadata.session,
            passthrough_args,
        )

    def prepare(self, worktree_dir: Path, preparation_argument: Path | None) -> None:
        """Best-effort run one preparation helper for a Git worktree."""
        preparation_path = resolve_preparation_path(
            preparation_argument,
            worktree_dir,
            require_executable=False,
        )
        if preparation_path is None:
            return
        try:
            result = subprocess.run(
                [str(preparation_path), "--target", str(worktree_dir)],
                check=False,
            )
        except OSError as error:
            self._warn_preparation_failure(preparation_path, str(error))
            return
        if result.returncode != 0:
            self._warn_preparation_failure(
                preparation_path,
                f"exit status {result.returncode}",
            )

    def pin(
        self,
        launcher: Path,
        session_id: str,
        expected_agent: AgentId | None,
        replace: bool,
    ) -> None:
        """Pin a launcher after validating its source-controlled agent identity."""
        metadata = self._source(launcher, expected_agent)
        if metadata.session is not None and metadata.session.value != session_id and not replace:
            raise LauncherError(
                "launcher already pins a different session; use --replace to change it"
            )
        write_launcher(
            launcher,
            replace_session(metadata, session_id),
            replace=True,
            mode=launcher_mode(launcher),
        )

    def sandbox(
        self,
        launcher: Path,
        mode: str | None,
        additional_dirs: tuple[str, ...],
        removed_dirs: tuple[str, ...],
    ) -> None:
        """Atomically update persisted sandbox settings on one launcher."""
        artifact = read_launcher_artifact(launcher)
        updated, unmatched_removals, removed_stored_directory = update_local_directories(
            artifact, additional_dirs, removed_dirs
        )
        if mode is not None:
            adapter = self._sandbox_adapter(updated.agent_id)
            adapter.validate_launcher_sandbox_mode(mode)
            updated = with_metadata_extension(updated, str(updated.agent_id), "sandbox", mode)
        if mode is None and not additional_dirs and not removed_stored_directory:
            self._warn_unmatched_removals(unmatched_removals)
            return
        write_launcher(
            launcher,
            updated,
            replace=True,
            mode=launcher_mode(launcher),
        )
        self._warn_unmatched_removals(unmatched_removals)

    def fork(
        self,
        launcher: Path,
        target_launcher: Path,
        expected_agent: AgentId | None,
        additional_dirs: tuple[str, ...],
        passthrough_args: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
        sandbox_mode: str | None = None,
        removed_dirs: tuple[str, ...] = (),
    ) -> SessionReference:
        """Create a child session and render a target launcher for it."""
        metadata = self._source(launcher, expected_agent)
        if metadata.session is None:
            raise LauncherError("source launcher has no pinned session")
        preflight_launcher_target(target_launcher)
        target, unmatched_removals, _ = update_local_directories(
            metadata, additional_dirs, removed_dirs
        )
        target = self._with_sandbox_mode(target, sandbox_mode)
        adapter = self._lifecycle_adapter(metadata.agent_id)
        self._run_preparation(metadata)
        session = adapter.fork_session(
            self._context(metadata, passthrough_args),
            self._settings(metadata.agent_id),
            metadata.session,
            passthrough_args,
        )
        access = git_metadata_access or launcher_git_metadata_access(metadata)
        target = replace_session(target, session.value)
        target = with_git_metadata_access(
            target,
            access,
        )
        write_launcher(target_launcher, target)
        self._warn_unmatched_removals(unmatched_removals)
        return session

    def adopt(
        self,
        launcher: Path,
        target_launcher: Path,
        session_id: str,
        expected_agent: AgentId | None,
        additional_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
        sandbox_mode: str | None = None,
        removed_dirs: tuple[str, ...] = (),
    ) -> None:
        """Create a target launcher for an existing same-worktree agent session."""
        metadata = self._source(launcher, expected_agent)
        target, unmatched_removals, _ = update_local_directories(
            metadata, additional_dirs, removed_dirs
        )
        target = self._with_sandbox_mode(target, sandbox_mode)
        adapter = self._lifecycle_adapter(metadata.agent_id)
        session = SessionReference(metadata.agent_id, session_id)
        record = adapter.find_session(self._settings(metadata.agent_id), session)
        if record.working_directory.resolve() != metadata.worktree_dir:
            raise LauncherError(
                f"session {session_id} belongs to {record.working_directory}, "
                f"not launcher worktree {metadata.worktree_dir}"
            )
        if metadata.session is not None and record.forked_from != metadata.session:
            if record.forked_from is None:
                print(
                    f"info: adopted session {session_id} has no parent; "
                    f"source launcher session is {metadata.session.value}"
                )
            else:
                print(
                    f"info: adopted session {session_id} forked from {record.forked_from.value}, "
                    f"not source launcher session {metadata.session.value}"
                )
        access = git_metadata_access or launcher_git_metadata_access(metadata)
        target = replace_session(target, session_id)
        target = with_git_metadata_access(
            target,
            access,
        )
        write_launcher(target_launcher, target)
        self._warn_unmatched_removals(unmatched_removals)

    def metadata(self, launcher: Path, expected_agent: AgentId | None = None) -> LauncherMetadata:
        """Read source metadata and validate an optional agent assertion."""
        return self._source(launcher, expected_agent)

    def _source(self, launcher: Path, expected_agent: AgentId | None) -> LauncherMetadata:
        metadata = read_launcher(launcher)
        if expected_agent is not None and metadata.agent_id != expected_agent:
            raise LauncherError(
                f"launcher agent is {metadata.agent_id}, not requested agent {expected_agent}"
            )
        return metadata

    def _context(self, metadata: LauncherMetadata, passthrough_args: tuple[str, ...]) -> RunContext:
        return RunContext(
            worktree_dir=metadata.worktree_dir,
            configured_writable_dirs=self._config.core.writable_dirs,
            requested_writable_dirs=tuple(str(path) for path in metadata.local_writable_dirs),
            passthrough_args=passthrough_args,
            git_metadata_access=launcher_git_metadata_access(metadata),
            launcher_extensions=metadata.extensions,
        )

    def _settings(self, agent_id: AgentId) -> Mapping[str, object]:
        return self._config.agent_settings.get(agent_id, {})

    def _runtime_adapter(self, agent_id: AgentId) -> RuntimeAgentAdapter:
        adapter = self._registry.get(agent_id)
        if not isinstance(adapter, RuntimeAgentAdapter):
            raise LauncherError(f"agent does not support launcher runtime: {agent_id}")
        return adapter

    def _lifecycle_adapter(self, agent_id: AgentId) -> SessionLifecycleAdapter:
        adapter = self._registry.get(agent_id)
        if not isinstance(adapter, SessionLifecycleAdapter):
            raise LauncherError(f"agent does not support launcher sessions: {agent_id}")
        return adapter

    def _sandbox_adapter(self, agent_id: AgentId) -> LauncherSandboxAdapter:
        adapter = self._registry.get(agent_id)
        if not isinstance(adapter, LauncherSandboxAdapter):
            raise LauncherError(
                f"agent does not support persisted launcher sandbox settings: {agent_id}"
            )
        return adapter

    def _with_sandbox_mode(
        self, metadata: LauncherMetadata, sandbox_mode: str | None
    ) -> LauncherMetadata:
        if sandbox_mode is None:
            return metadata
        adapter = self._sandbox_adapter(metadata.agent_id)
        adapter.validate_launcher_sandbox_mode(sandbox_mode)
        return with_metadata_extension(metadata, str(metadata.agent_id), "sandbox", sandbox_mode)

    def _warn_unmatched_removals(self, directories: tuple[Path, ...]) -> None:
        for directory in directories:
            print(
                f"warning: launcher-local writable directory is not stored: {directory}",
                file=sys.stderr,
            )

    def _warn_preparation_failure(self, preparation_path: Path, reason: str) -> None:
        print(
            f"warning: launcher preparation failed; continuing: {preparation_path}: {reason}",
            file=sys.stderr,
        )

    def _run_preparation(self, metadata: LauncherMetadata) -> None:
        self.prepare(metadata.worktree_dir, metadata.preparation_path)
