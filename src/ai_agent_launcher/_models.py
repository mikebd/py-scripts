"""Agent-neutral value types used by the launcher core."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import override

_AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class GitMetadataAccess(StrEnum):
    """The Git metadata visibility granted to an agent runtime."""

    WORKTREE = "worktree"
    SHARED = "shared"


@dataclass(frozen=True, order=True)
class AgentId:
    """A stable, user-facing identifier for an agent implementation."""

    value: str

    def __post_init__(self) -> None:
        if not _AGENT_ID_PATTERN.fullmatch(self.value):
            message = (
                "agent identifiers must start with a lowercase letter and contain only "
                "lowercase letters, digits, or hyphens"
            )
            raise ValueError(message)

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SessionReference:
    """An opaque session reference associated with the agent that created it."""

    agent_id: AgentId
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("session references must not be empty")
