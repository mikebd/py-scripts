"""Built-in adapter registrations."""

from ai_agent_launcher._codex import CodexAdapter
from ai_agent_launcher._registry import AgentRegistry


def default_registry() -> AgentRegistry:
    """Return the immutable registry supported by this release."""
    return AgentRegistry((CodexAdapter(),))
