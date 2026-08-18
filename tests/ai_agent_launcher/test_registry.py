from dataclasses import dataclass

import pytest

from ai_agent_launcher._codex import CodexAdapter
from ai_agent_launcher._defaults import default_registry
from ai_agent_launcher._models import AgentId
from ai_agent_launcher._registry import AgentRegistry, DuplicateAgentError, UnknownAgentError


@dataclass(frozen=True)
class ExampleAdapter:
    identifier: AgentId


def test_default_registry_contains_only_the_initial_adapter() -> None:
    registry = default_registry()

    assert registry.identifiers == (AgentId("codex"),)
    assert isinstance(registry.get(AgentId("codex")), CodexAdapter)


def test_registry_uses_stable_identifier_order_and_a_non_codex_adapter() -> None:
    alpha = ExampleAdapter(AgentId("alpha"))
    zulu = ExampleAdapter(AgentId("zulu"))
    registry = AgentRegistry((zulu, alpha))

    assert registry.identifiers == (AgentId("alpha"), AgentId("zulu"))
    assert registry.get(AgentId("alpha")) is alpha


def test_registry_rejects_duplicate_identifiers() -> None:
    with pytest.raises(DuplicateAgentError, match="duplicate agent identifier: codex"):
        AgentRegistry((ExampleAdapter(AgentId("codex")), ExampleAdapter(AgentId("codex"))))


def test_registry_rejects_an_invalid_adapter_identifier_type() -> None:
    with pytest.raises(TypeError, match="AgentId"):
        AgentRegistry((ExampleAdapter("codex"),))  # type: ignore[arg-type]


def test_registry_reports_unknown_identifier_and_available_choices() -> None:
    registry = AgentRegistry((ExampleAdapter(AgentId("codex")),))

    with pytest.raises(UnknownAgentError, match="unknown agent identifier other") as error:
        registry.get(AgentId("other"))

    assert "available identifiers: codex" in str(error.value)
