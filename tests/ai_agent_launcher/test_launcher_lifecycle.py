from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_agent_launcher import _codex
from ai_agent_launcher._launchers import read_launcher
from ai_agent_launcher.cli import main


@pytest.fixture()
def git_worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=worktree, check=True
    )
    subprocess.run(["git", "config", "user.name", "Launcher Test"], cwd=worktree, check=True)
    (worktree / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=worktree, check=True)
    return worktree


def _disable_optional_cache_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    original_which = _codex.shutil.which

    def which(command: str) -> str | None:
        if command in {"go", "golangci-lint"}:
            return None
        return original_which(command)

    monkeypatch.setattr(_codex.shutil, "which", which)


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "\n".join(
            (
                f"#!{sys.executable}",
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                "arguments = sys.argv[1:]",
                "if arguments and arguments[0] == 'fork':",
                "    sessions = Path(os.environ['CODEX_HOME']) / 'sessions'",
                "    sessions.mkdir(parents=True, exist_ok=True)",
                "    (sessions / 'child.jsonl').write_text(json.dumps({",
                "        'type': 'session_meta',",
                "        'payload': {",
                "            'id': 'child-session',",
                "            'cwd': os.getcwd(),",
                "            'forked_from_id': 'parent-session',",
                "        },",
                "    }) + '\\n', encoding='utf-8')",
                "output = Path(os.environ['FAKE_CODEX_OUTPUT'])",
                "output.write_text(json.dumps(arguments), encoding='utf-8')",
            )
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _config(path: Path, executable: Path, home: Path) -> None:
    path.write_text(
        "\n".join(
            (
                "[core]",
                "writable_dirs = []",
                "",
                "[agents.codex]",
                f'executable = "{executable}"',
                f'home = "{home}"',
                "use_rtk = false",
            )
        ),
        encoding="utf-8",
    )


def test_create_and_pin_preserve_versioned_metadata(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    launcher = tmp_path / "launcher"

    assert (
        main(
            [
                "launcher",
                "create",
                "--agent",
                "codex",
                "--launcher",
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
                "--marker",
                "# launcher marker",
                "--add-dir",
                str(local_dir),
            ]
        )
        == 0
    )
    assert launcher.stat().st_mode & 0o777 == 0o700
    assert 'exec ai-agent-launcher launcher run --launcher "$0" -- "$@"' in launcher.read_text(
        encoding="utf-8"
    )
    assert read_launcher(launcher).session is None

    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "one"]) == 0
    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "one"]) == 0
    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "two"]) == 2
    assert "use --replace" in capsys.readouterr().err
    assert (
        main(
            [
                "launcher",
                "pin",
                "--launcher",
                str(launcher),
                "--session-id",
                "two",
                "--replace",
            ]
        )
        == 0
    )
    pinned = read_launcher(launcher).session
    assert pinned is not None
    assert pinned.value == "two"


def test_generated_shim_delegates_through_path(git_worktree: Path, tmp_path: Path) -> None:
    launcher = tmp_path / "launcher"
    capture = tmp_path / "capture"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "ai-agent-launcher"
    command.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$LAUNCHER_CAPTURE"\n', encoding="utf-8")
    command.chmod(0o755)
    assert (
        main(
            [
                "launcher",
                "create",
                "--agent",
                "codex",
                "--launcher",
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
                "--marker",
                "# launcher marker",
            ]
        )
        == 0
    )

    environment = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LAUNCHER_CAPTURE": str(capture),
    }
    subprocess.run(["/bin/sh", str(launcher), "continue"], check=True, env=environment)

    assert capture.read_text(encoding="utf-8").splitlines() == [
        "launcher",
        "run",
        "--launcher",
        str(launcher),
        "--",
        "continue",
    ]


def test_fork_prepares_worktree_and_creates_child_launcher(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = _fake_codex(tmp_path)
    config_path = tmp_path / "config.toml"
    home = tmp_path / "codex-home"
    _config(config_path, executable, home)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    inherited = tmp_path / "inherited"
    added = tmp_path / "added"
    inherited.mkdir()
    added.mkdir()
    preparation = tmp_path / "prepare"
    prepared = tmp_path / "prepared"
    preparation.write_text('#!/bin/sh\nprintf \'%s\' "$2" > "$PREPARED_OUTPUT"\n', encoding="utf-8")
    preparation.chmod(0o755)
    output = tmp_path / "fake-codex.json"
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
    monkeypatch.setenv("PREPARED_OUTPUT", str(prepared))
    _disable_optional_cache_tools(monkeypatch)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "create",
                "--agent",
                "codex",
                "--launcher",
                str(source),
                "--worktree-dir",
                str(git_worktree),
                "--marker",
                "# launcher marker",
                "--prepare",
                str(preparation),
                "--add-dir",
                str(inherited),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "pin",
                "--launcher",
                str(source),
                "--session-id",
                "parent-session",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "fork",
                "--launcher",
                str(source),
                "--target-launcher",
                str(target),
                "--add-dir",
                str(inherited),
                "--add-dir",
                str(added),
                "--",
                "continue",
            ]
        )
        == 0
    )

    assert prepared.read_text(encoding="utf-8") == str(git_worktree)
    assert json.loads(output.read_text(encoding="utf-8"))[0] == "fork"
    target_metadata = read_launcher(target)
    assert target_metadata.session is not None
    assert target_metadata.session.value == "child-session"
    assert target_metadata.local_writable_dirs == (inherited.resolve(), added.resolve())


def test_adopt_requires_same_worktree_and_reports_parent_mismatch(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "codex-home"
    session_file = home / "sessions" / "existing.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "existing-session",
                    "cwd": str(git_worktree),
                    "forked_from_id": "unrelated-parent",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    _config(config_path, tmp_path / "unused-codex", home)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "create",
                "--agent",
                "codex",
                "--launcher",
                str(source),
                "--worktree-dir",
                str(git_worktree),
                "--marker",
                "# launcher marker",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "pin",
                "--launcher",
                str(source),
                "--session-id",
                "parent-session",
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "adopt",
                "--launcher",
                str(source),
                "--target-launcher",
                str(target),
                "--session-id",
                "existing-session",
            ]
        )
        == 0
    )
    assert "unrelated-parent" in capsys.readouterr().out
    assert read_launcher(target).session is not None
