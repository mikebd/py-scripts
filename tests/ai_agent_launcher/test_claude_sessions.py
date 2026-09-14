from pathlib import Path

import pytest

from ai_agent_launcher._claude_sessions import ClaudeSessionCatalog
from ai_agent_launcher._errors import LauncherError


def test_session_catalog_reads_cwd_and_continued_in_links(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-tmp-worktree"
    project.mkdir(parents=True)
    (project / "parent.jsonl").write_text(
        "\n".join(
            [
                '{"sessionId":"parent-id","cwd":"/tmp/worktree"}',
                '{"type":"continued-in","sessionId":"parent-id","continuedInSessionId":"child-id"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "child.jsonl").write_text(
        '{"sessionId":"child-id","cwd":"/tmp/worktree"}\n',
        encoding="utf-8",
    )

    records = ClaudeSessionCatalog(tmp_path).records()

    assert [record.identifier for record in records] == ["child-id", "parent-id"]
    child = next(record for record in records if record.identifier == "child-id")
    parent = next(record for record in records if record.identifier == "parent-id")
    assert child.forked_from_identifier == "parent-id"
    assert parent.forked_from_identifier is None
    assert ClaudeSessionCatalog(tmp_path).find_unique("parent-id").working_directory == Path(
        "/tmp/worktree"
    )


def test_session_catalog_ignores_malformed_and_incomplete_records(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-tmp-worktree"
    project.mkdir(parents=True)
    (project / "broken.jsonl").write_text("not json\n", encoding="utf-8")
    (project / "incomplete.jsonl").write_text('{"sessionId":"missing-cwd"}\n', encoding="utf-8")

    assert ClaudeSessionCatalog(tmp_path).records() == ()


def test_session_catalog_ignores_invalid_utf8_and_keeps_valid_records(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-tmp-worktree"
    project.mkdir(parents=True)
    (project / "invalid.jsonl").write_bytes(b"\xff\xfe\n")
    (project / "valid.jsonl").write_text(
        '{"sessionId":"valid","cwd":"/tmp/worktree"}\n', encoding="utf-8"
    )

    records = ClaudeSessionCatalog(tmp_path).records()

    assert [record.identifier for record in records] == ["valid"]


def test_session_catalog_rejects_ambiguous_identifier(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-tmp-worktree"
    project.mkdir(parents=True)
    contents = '{"sessionId":"duplicate","cwd":"/tmp/worktree"}\n'
    (project / "one.jsonl").write_text(contents, encoding="utf-8")
    (project / "two.jsonl").write_text(contents, encoding="utf-8")

    with pytest.raises(LauncherError, match="expected one"):
        ClaudeSessionCatalog(tmp_path).find_unique("duplicate")


def test_session_catalog_reports_missing_identifier(tmp_path: Path) -> None:
    with pytest.raises(LauncherError, match="no Claude session metadata found"):
        ClaudeSessionCatalog(tmp_path).find_unique("missing")
