"""Agent-neutral generated-launcher lifecycle orchestration."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from ai_agent_launcher._adapters import RuntimeAgentAdapter, SessionLifecycleAdapter
from ai_agent_launcher._config import LauncherConfig
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import (
    LauncherMetadata,
    build_metadata,
    launcher_git_metadata_access,
    launcher_mode,
    preflight_launcher_target,
    read_launcher,
    replace_session,
    with_git_metadata_access,
    with_local_directories,
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
        marker: str,
        preparation_path: Path | None,
        local_writable_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
    ) -> Path:
        """Create an initially unpinned launcher for an existing worktree."""
        self._runtime_adapter(agent_id)
        metadata = build_metadata(
            agent_id,
            worktree_dir,
            marker,
            preparation_path,
            local_writable_dirs,
        )
        access = git_metadata_access or self._config.core.default_git_metadata_access
        return write_launcher(launcher, with_git_metadata_access(metadata, access))

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

    def prepare(self, worktree_dir: Path, preparation_path: Path | None) -> None:
        """Run one validated launcher preparation helper for a Git worktree."""
        if preparation_path is None:
            return
        try:
            result = subprocess.run(
                [str(preparation_path), "--target", str(worktree_dir)],
                check=False,
            )
        except OSError as error:
            raise LauncherError(f"unable to run launcher preparation: {error}") from error
        if result.returncode != 0:
            raise LauncherError(f"launcher preparation failed with exit status {result.returncode}")

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

    def fork(
        self,
        launcher: Path,
        target_launcher: Path,
        expected_agent: AgentId | None,
        additional_dirs: tuple[str, ...],
        passthrough_args: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
    ) -> SessionReference:
        """Create a child session and render a target launcher for it."""
        metadata = self._source(launcher, expected_agent)
        if metadata.session is None:
            raise LauncherError("source launcher has no pinned session")
        preflight_launcher_target(target_launcher)
        adapter = self._lifecycle_adapter(metadata.agent_id)
        self._run_preparation(metadata)
        session = adapter.fork_session(
            self._context(metadata, passthrough_args),
            self._settings(metadata.agent_id),
            metadata.session,
            passthrough_args,
        )
        access = git_metadata_access or launcher_git_metadata_access(metadata)
        target = replace_session(with_local_directories(metadata, additional_dirs), session.value)
        target = with_git_metadata_access(
            target,
            access,
        )
        write_launcher(target_launcher, target)
        return session

    def adopt(
        self,
        launcher: Path,
        target_launcher: Path,
        session_id: str,
        expected_agent: AgentId | None,
        additional_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None = None,
    ) -> None:
        """Create a target launcher for an existing same-worktree agent session."""
        metadata = self._source(launcher, expected_agent)
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
        target = replace_session(with_local_directories(metadata, additional_dirs), session_id)
        target = with_git_metadata_access(
            target,
            access,
        )
        write_launcher(target_launcher, target)

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

    def _run_preparation(self, metadata: LauncherMetadata) -> None:
        self.prepare(metadata.worktree_dir, metadata.preparation_path)
