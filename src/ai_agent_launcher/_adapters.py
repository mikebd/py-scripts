"""Internal contracts for agent-specific launcher behavior."""

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_agent_launcher._models import AgentId, SessionReference
from ai_agent_launcher._runtime import RunContext


class AgentAdapter(Protocol):
    """Identifies an agent implementation known to the launcher."""

    @property
    def identifier(self) -> AgentId:
        """Return the immutable identifier for this agent."""
        ...


@runtime_checkable
class RuntimeAgentAdapter(AgentAdapter, Protocol):
    """Internal extension point for an adapter that can service `run`."""

    def configure_run_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add this adapter's command-line options to the run parser."""
        ...

    def run(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        arguments: argparse.Namespace,
    ) -> int:
        """Run the selected agent and return its process exit status."""
        ...

    def run_launcher(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        session: SessionReference | None,
        passthrough_args: tuple[str, ...],
    ) -> int:
        """Run a generated launcher without exposing agent-specific options to core."""
        ...


@dataclass(frozen=True)
class WritableDirectoryReport:
    """Best-effort agent-owned writable-directory resolution results."""

    directories: tuple[Path, ...]
    notes: tuple[str, ...]


@runtime_checkable
class WritableDirectoryAdapter(AgentAdapter, Protocol):
    """Internal extension point for reporting effective writable directories."""

    def resolve_writable_dirs(
        self,
        context: RunContext,
        settings: Mapping[str, object],
    ) -> WritableDirectoryReport:
        """Resolve writable directories without starting an agent or modifying the filesystem."""
        ...


@dataclass(frozen=True)
class AgentSessionMetadata:
    """Agent-neutral session facts used by generated launcher lifecycle commands."""

    session: SessionReference
    working_directory: Path
    forked_from: SessionReference | None


@runtime_checkable
class SessionLifecycleAdapter(RuntimeAgentAdapter, Protocol):
    """Runtime adapter extension for session-aware launcher operations."""

    def fork_session(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        parent: SessionReference,
        passthrough_args: tuple[str, ...],
    ) -> SessionReference:
        """Start and identify exactly one child session."""
        ...

    def find_session(
        self, settings: Mapping[str, object], session: SessionReference
    ) -> AgentSessionMetadata:
        """Find exactly one session metadata record by opaque agent session reference."""
        ...
