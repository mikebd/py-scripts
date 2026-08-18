from pathlib import Path

import pytest

from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._sessions import CodexSessionCatalog


def test_session_catalog_reads_payload_and_direct_metadata(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions" / "2026" / "08" / "18"
    sessions.mkdir(parents=True)
    (sessions / "payload.jsonl").write_text(
        '{"type":"session_meta","payload":{"id":"payload-id","cwd":"/tmp/payload"}}\n',
        encoding="utf-8",
    )
    (sessions / "direct.jsonl").write_text(
        '{"id":"direct-id","cwd":"/tmp/direct","forked_from_id":"parent"}\n',
        encoding="utf-8",
    )

    records = CodexSessionCatalog(tmp_path).records()

    assert [record.identifier for record in records] == ["direct-id", "payload-id"]
    assert records[0].forked_from_identifier == "parent"
    assert CodexSessionCatalog(tmp_path).find_unique("payload-id").working_directory == Path(
        "/tmp/payload"
    )


def test_session_catalog_ignores_malformed_and_unrelated_records(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "broken.jsonl").write_text("not json\n", encoding="utf-8")
    (sessions / "event.jsonl").write_text('{"type":"event","payload":{}}\n', encoding="utf-8")

    assert CodexSessionCatalog(tmp_path).records() == ()


def test_session_catalog_rejects_ambiguous_identifier(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    contents = '{"type":"session_meta","payload":{"id":"duplicate","cwd":"/tmp/worktree"}}\n'
    (sessions / "one.jsonl").write_text(contents, encoding="utf-8")
    (sessions / "two.jsonl").write_text(contents, encoding="utf-8")

    with pytest.raises(LauncherError, match="expected one"):
        CodexSessionCatalog(tmp_path).find_unique("duplicate")
