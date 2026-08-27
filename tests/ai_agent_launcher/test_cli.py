from importlib.metadata import version

import pytest
import shtab
from pytest_mock import MockerFixture

from ai_agent_launcher.cli import (
    _COMPLETION_SHELLS,
    _normalize_worktree_suffix,
    distribution_version,
    main,
)


def test_empty_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("usage: ai-agent-launcher")
    assert "--version" in captured.out
    assert "completion" in captured.out
    assert "migrate" not in captured.out
    assert captured.err == ""


def test_completion_shells_follow_shtab() -> None:
    assert _COMPLETION_SHELLS == tuple(sorted(shtab.SUPPORTED_SHELLS))


@pytest.mark.parametrize("shell", _COMPLETION_SHELLS)
def test_completion_generates_script_for_supported_shell(
    capsys: pytest.CaptureFixture[str], shell: str
) -> None:
    assert main(["completion", "--shell", shell]) == 0

    captured = capsys.readouterr()
    assert "ai-agent-launcher" in captured.out
    assert "launcher" in captured.out
    assert "worktree" in captured.out
    assert "--marker" not in captured.out
    assert captured.err == ""


def test_completion_help_lists_supported_shells(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["completion", "--help"])

    assert "{" + ",".join(_COMPLETION_SHELLS) + "}" in capsys.readouterr().out


@pytest.mark.parametrize("shell", _COMPLETION_SHELLS)
def test_completion_detects_shell(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, shell: str
) -> None:
    monkeypatch.setenv("SHELL", f"/usr/bin/{shell}")

    assert main(["completion"]) == 0
    assert "ai-agent-launcher" in capsys.readouterr().out


def test_completion_explicit_shell_overrides_detected_shell(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    complete = mocker.patch("ai_agent_launcher.cli.shtab.complete", return_value="completion")

    assert main(["completion", "--shell", "fish"]) == 0

    complete.assert_called_once()
    assert complete.call_args.kwargs["shell"] == "fish"
    assert capsys.readouterr().out == "completion"


@pytest.mark.parametrize("shell", (None, "/usr/bin/ksh"))
def test_completion_requires_detectable_supported_shell(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    if shell is None:
        monkeypatch.delenv("SHELL", raising=False)
    else:
        monkeypatch.setenv("SHELL", shell)

    with pytest.raises(SystemExit, match="2"):
        main(["completion"])

    assert "--shell" in capsys.readouterr().err


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


def test_worktree_requires_a_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["worktree"])

    assert "worktree_command" in capsys.readouterr().err


def test_launcher_help_lists_describe(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["launcher", "--help"])

    assert "describe" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    (
        ("launcher", "create", "--help"),
        ("worktree", "new", "--help"),
        ("worktree", "stack", "--help"),
    ),
)
def test_launcher_creation_help_omits_marker(
    arguments: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(list(arguments))

    assert "--marker" not in capsys.readouterr().out


def test_launcher_create_help_lists_session_id(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["launcher", "create", "--help"])

    assert "--session-id" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "launcher",
            "create",
            "--agent",
            "codex",
            "--launcher",
            "/tmp/launcher",
            "--worktree-dir",
            "/tmp/worktree",
            "--session-id",
            "",
        ),
        ("launcher", "pin", "--launcher", "/tmp/launcher", "--session-id", ""),
        (
            "launcher",
            "adopt",
            "--launcher",
            "/tmp/launcher",
            "--target-launcher",
            "/tmp/target-launcher",
            "--session-id",
            "",
        ),
    ),
)
def test_launcher_lifecycle_commands_reject_empty_session_ids(
    arguments: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(list(arguments))

    assert "session ID must not be empty" in capsys.readouterr().err


@pytest.mark.parametrize("command", ("new", "stack"))
def test_worktree_creation_help_omits_session_id(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["worktree", command, "--help"])

    assert "--session-id" not in capsys.readouterr().out


def test_launcher_create_rejects_removed_marker_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "launcher",
                "create",
                "--agent",
                "codex",
                "--launcher",
                "/tmp/launcher",
                "--worktree-dir",
                "/tmp/worktree",
                "--marker",
                "# legacy marker",
            ]
        )

    assert "unrecognized arguments: --marker # legacy marker" in capsys.readouterr().err


def test_launcher_sandbox_help_lists_persistent_update_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["launcher", "sandbox", "--help"])

    help_text = capsys.readouterr().out
    assert "--launcher" in help_text
    assert "--mode" in help_text
    assert "--add-dir" in help_text
    assert "--remove-dir" in help_text
    assert "--sandbox-mode" not in help_text.split()
    assert "{danger-full-access,read-only,workspace-write}" in help_text


@pytest.mark.parametrize(
    ("arguments", "expects_remove_dir"),
    (
        (("launcher", "create", "--help"), False),
        (("launcher", "fork", "--help"), True),
        (("launcher", "adopt", "--help"), True),
        (("worktree", "new", "--help"), False),
        (("worktree", "stack", "--help"), False),
    ),
)
def test_launcher_creation_help_lists_sandbox_mode(
    arguments: tuple[str, ...], expects_remove_dir: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(list(arguments))

    help_text = capsys.readouterr().out
    assert "--sandbox-mode" in help_text
    assert ("--remove-dir" in help_text) is expects_remove_dir
    assert "--mode" not in help_text.split()


def test_strict_stack_help_omits_target_overrides(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["worktree", "stack", "--help"])

    help_text = capsys.readouterr().out
    assert "--launcher" not in help_text
    assert "--branch" not in help_text
    assert "--from" not in help_text
    assert "--source-worktree-dir" not in help_text


def test_new_help_includes_source_worktree_dir(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["worktree", "new", "--help"])

    assert "--source-worktree-dir" in capsys.readouterr().out


def test_suffix_normalization_leaves_non_worktree_passthrough_unchanged() -> None:
    arguments = ["run", "--agent", "codex", "--", "--suffix", "-child"]

    assert _normalize_worktree_suffix(arguments) == arguments


def test_suffix_normalization_stops_at_separator() -> None:
    arguments = ["worktree", "stack", "--suffix", "-child", "--", "--suffix", "-inner"]

    assert _normalize_worktree_suffix(arguments) == [
        "worktree",
        "stack",
        "--suffix=-child",
        "--",
        "--suffix",
        "-inner",
    ]


def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])

    help_text = capsys.readouterr().out
    assert "usage: ai-agent-launcher" in help_text
    assert "Agent runtime activation guide:" in help_text
    assert (
        "https://github.com/mikebd/ai-agent-skills/blob/main/"
        "shared/references/agent-runtime/AI_AGENT_LAUNCHER.md"
    ) in help_text


def test_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])

    assert capsys.readouterr().out.strip() == distribution_version()


def test_distribution_version_comes_from_package_metadata() -> None:
    assert distribution_version() == version("mikebd-py-scripts")
