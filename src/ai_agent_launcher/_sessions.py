"""Codex session JSONL discovery kept behind the Codex adapter boundary."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import LauncherError


@dataclass(frozen=True)
class CodexSessionMetadata:
    """The stable metadata needed by future Codex session workflows."""

    identifier: str
    working_directory: Path
    forked_from_identifier: str | None
    source_file: Path


class CodexSessionCatalog:
    """Read session metadata without creating, mutating, or selecting sessions."""

    def __init__(self, codex_home: Path) -> None:
        self._sessions_dir = codex_home / "sessions"

    def records(self) -> tuple[CodexSessionMetadata, ...]:
        """Return well-formed session metadata records in stable path order."""
        if not self._sessions_dir.is_dir():
            return ()
        records: list[CodexSessionMetadata] = []
        for source_file in sorted(self._sessions_dir.rglob("*.jsonl")):
            record = _read_session_metadata(source_file)
            if record is not None:
                records.append(record)
        return tuple(records)

    def find_unique(self, identifier: str) -> CodexSessionMetadata:
        """Return exactly one matching record or explain why it is unusable."""
        matches = [record for record in self.records() if record.identifier == identifier]
        if len(matches) == 0:
            raise LauncherError(f"no Codex session metadata found for {identifier}")
        if len(matches) != 1:
            raise LauncherError(
                f"expected one Codex session metadata file for {identifier}, found {len(matches)}"
            )
        return matches[0]


def _read_session_metadata(source_file: Path) -> CodexSessionMetadata | None:
    try:
        with source_file.open(encoding="utf-8") as session_file:
            first_line = session_file.readline()
        document = _object_mapping(json.loads(first_line))
    except (OSError, json.JSONDecodeError):
        return None
    if document is None:
        return None
    if "type" in document and document["type"] != "session_meta":
        return None

    payload = _object_mapping(document.get("payload", document))
    if payload is None:
        return None
    identifier = payload.get("id")
    working_directory = payload.get("cwd")
    forked_from_identifier = payload.get("forked_from_id")
    if not isinstance(identifier, str) or not identifier:
        return None
    if not isinstance(working_directory, str) or not working_directory:
        return None
    if forked_from_identifier is not None and not isinstance(forked_from_identifier, str):
        return None
    return CodexSessionMetadata(
        identifier=identifier,
        working_directory=Path(working_directory),
        forked_from_identifier=forked_from_identifier,
        source_file=source_file,
    )


def _object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapping: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            return None
        mapping[key] = item
    return mapping
