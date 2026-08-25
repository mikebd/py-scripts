import pytest

from ai_agent_launcher._models import AgentId, SessionReference


@pytest.mark.parametrize("value", ["codex", "agent-2", "x9"])
def test_agent_identifier_accepts_lowercase_hyphenated_names(value: str) -> None:
    assert str(AgentId(value)) == value


@pytest.mark.parametrize("value", ["", "Codex", "agent_name", "-agent"])
def test_agent_identifier_rejects_invalid_names(value: str) -> None:
    with pytest.raises(ValueError, match="agent identifiers"):
        AgentId(value)


def test_session_reference_keeps_its_agent_and_opaque_value() -> None:
    reference = SessionReference(agent_id=AgentId("codex"), value="session/opaque:ref")

    assert reference.agent_id == AgentId("codex")
    assert reference.value == "session/opaque:ref"


def test_session_reference_rejects_an_empty_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SessionReference(agent_id=AgentId("codex"), value="")
