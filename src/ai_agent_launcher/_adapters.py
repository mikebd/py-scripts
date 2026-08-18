"""Internal contracts for agent-specific launcher behavior."""

from typing import Protocol

from ai_agent_launcher._models import AgentId


class AgentAdapter(Protocol):
    """Identifies an agent implementation known to the launcher."""

    @property
    def identifier(self) -> AgentId:
        """Return the immutable identifier for this agent."""
        ...
