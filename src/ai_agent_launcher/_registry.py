"""Immutable registry of launcher adapters."""

from collections.abc import Iterable
from types import MappingProxyType
from typing import cast

from ai_agent_launcher._adapters import AgentAdapter
from ai_agent_launcher._models import AgentId


class DuplicateAgentError(ValueError):
    """Raised when more than one adapter has the same identifier."""


class UnknownAgentError(LookupError):
    """Raised when an adapter was requested that is not registered."""


class AgentRegistry:
    """An immutable lookup table built from an explicit adapter collection."""

    def __init__(self, adapters: Iterable[AgentAdapter]) -> None:
        registered: dict[AgentId, AgentAdapter] = {}
        for adapter in adapters:
            identifier = adapter.identifier
            if not isinstance(cast(object, identifier), AgentId):
                raise TypeError("adapter identifiers must be AgentId instances")
            if identifier in registered:
                raise DuplicateAgentError(f"duplicate agent identifier: {identifier}")
            registered[identifier] = adapter

        self._by_identifier = MappingProxyType(registered)
        self._identifiers = tuple(sorted(registered))

    @property
    def identifiers(self) -> tuple[AgentId, ...]:
        """Return registered identifiers in stable lexical order."""
        return self._identifiers

    def get(self, identifier: AgentId) -> AgentAdapter:
        """Return an adapter or report the available identifiers."""
        try:
            return self._by_identifier[identifier]
        except KeyError as error:
            available = ", ".join(str(value) for value in self._identifiers) or "none"
            raise UnknownAgentError(
                f"unknown agent identifier {identifier!s}; available identifiers: {available}"
            ) from error
