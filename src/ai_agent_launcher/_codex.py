"""Identity-only adapter for the initially supported agent."""

from dataclasses import dataclass

from ai_agent_launcher._models import AgentId

_CODEX_IDENTIFIER = AgentId("codex")


@dataclass(frozen=True)
class CodexAdapter:
    """Register Codex without defining any of its runtime behavior."""

    @property
    def identifier(self) -> AgentId:
        """Return the adapter's stable agent identifier."""
        return _CODEX_IDENTIFIER
