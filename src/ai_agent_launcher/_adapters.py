"""Internal contracts for agent-specific launcher behavior."""

import argparse
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ai_agent_launcher._models import AgentId
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
