"""Claude Code session JSONL discovery kept behind the Claude adapter boundary."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ai_agent_launcher._errors import LauncherError


@dataclass(frozen=True)
class ClaudeSessionMetadata:
    """The stable metadata needed by future Claude session workflows."""

    identifier: str
    working_directory: Path
    forked_from_identifier: str | None
    source_file: Path


class ClaudeSessionCatalog:
    """Read session metadata without creating, mutating, or selecting sessions."""

    def __init__(self, claude_home: Path) -> None:
        self._projects_dir = claude_home / "projects"

    def records(self) -> tuple[ClaudeSessionMetadata, ...]:
        """Return well-formed session metadata records in stable path order."""
        if not self._projects_dir.is_dir():
            return ()
        source_files = sorted(self._projects_dir.glob("*/*.jsonl"))
        parents_by_child = _read_continued_in_links(source_files)
        records: list[ClaudeSessionMetadata] = []
        for source_file in source_files:
            record = _read_session_metadata(source_file, parents_by_child)
            if record is not None:
                records.append(record)
        return tuple(records)

    def find_unique(self, identifier: str) -> ClaudeSessionMetadata:
        """Return exactly one matching record or explain why it is unusable."""
        matches = [record for record in self.records() if record.identifier == identifier]
        if len(matches) == 0:
            raise LauncherError(f"no Claude session metadata found for {identifier}")
        if len(matches) != 1:
            raise LauncherError(
                f"expected one Claude session metadata file for {identifier}, found {len(matches)}"
            )
        return matches[0]


def _read_continued_in_links(source_files: list[Path]) -> dict[str, str]:
    """Map a child session identifier to its parent from `continued-in` records."""
    parents_by_child: dict[str, str] = {}
    for source_file in source_files:
        try:
            with source_file.open(encoding="utf-8") as session_file:
                for line in session_file:
                    document = _object_mapping(_json_loads(line))
                    if document is None:
                        continue
                    if document.get("type") != "continued-in":
                        continue
                    parent = document.get("sessionId")
                    child = document.get("continuedInSessionId")
                    if isinstance(parent, str) and parent and isinstance(child, str) and child:
                        parents_by_child[child] = parent
        except (OSError, UnicodeDecodeError):
            continue
    return parents_by_child


def _read_session_metadata(
    source_file: Path, parents_by_child: dict[str, str]
) -> ClaudeSessionMetadata | None:
    identifier: str | None = None
    working_directory: str | None = None
    try:
        with source_file.open(encoding="utf-8") as session_file:
            for line in session_file:
                document = _object_mapping(_json_loads(line))
                if document is None:
                    continue
                session_id = document.get("sessionId")
                if isinstance(session_id, str) and session_id:
                    identifier = session_id
                cwd = document.get("cwd")
                if isinstance(cwd, str) and cwd:
                    working_directory = cwd
                if identifier is not None and working_directory is not None:
                    break
    except (OSError, UnicodeDecodeError):
        return None
    if identifier is None or working_directory is None:
        return None
    return ClaudeSessionMetadata(
        identifier=identifier,
        working_directory=Path(working_directory),
        forked_from_identifier=parents_by_child.get(identifier),
        source_file=source_file,
    )


def _json_loads(line: str) -> object:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapping: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            return None
        mapping[key] = item
    return mapping
