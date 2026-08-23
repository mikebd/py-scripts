from importlib.metadata import version

import pytest

from ai_agent_launcher.cli import _normalize_worktree_suffix, distribution_version, main


def test_empty_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("usage: ai-agent-launcher")
    assert "--version" in captured.out
    assert "migrate" not in captured.out
    assert captured.err == ""


def test_run_help_lists_runtime_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["run", "--help"])

    help_text = capsys.readouterr().out
    assert "--agent" in help_text
    assert "--reasoning-effort" in help_text
    assert "--fork-session-id" in help_text


def test_worktree_help_lists_new_and_stack(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["worktree", "--help"])

    help_text = capsys.readouterr().out
    assert "new" in help_text
    assert "stack" in help_text


def test_strict_stack_help_omits_target_overrides(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["worktree", "stack", "--help"])

    help_text = capsys.readouterr().out
    assert "--launcher" not in help_text
    assert "--branch" not in help_text
    assert "--from" not in help_text


def test_suffix_normalization_preserves_agent_passthrough() -> None:
    arguments = ["run", "--agent", "codex", "--", "--suffix", "-child"]

    assert _normalize_worktree_suffix(arguments) == arguments


def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])

    assert "usage: ai-agent-launcher" in capsys.readouterr().out


def test_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])

    assert capsys.readouterr().out.strip() == distribution_version()


def test_distribution_version_comes_from_package_metadata() -> None:
    assert distribution_version() == version("mikebd-py-scripts")
