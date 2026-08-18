from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_agent_launcher import _codex
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
    (worktree / ".context").mkdir()
    subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=worktree, check=True)
    return worktree


def _fake_codex(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "fake-output.json"
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                "Path(os.environ['FAKE_CODEX_OUTPUT']).write_text(json.dumps({",
                "    'argv': sys.argv[1:],",
                "    'cwd': os.getcwd(),",
                "    'codex_home': os.environ.get('CODEX_HOME'),",
                "    'use_rtk': os.environ.get('USE_RTK'),",
                "    'rust_log': os.environ.get('RUST_LOG'),",
                "}), encoding='utf-8')",
                "raise SystemExit(int(os.environ.get('FAKE_CODEX_EXIT', '0')))",
            ]
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, output


def _write_config(path: Path, executable: Path, home: Path, writable_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[core]",
                f'writable_dirs = ["{writable_dir}"]',
                "",
                "[agents.codex]",
                f'executable = "{executable}"',
                f'home = "{home}"',
                'sandbox = "read-only"',
                'model = "config-model"',
                'reasoning_effort = "low"',
                "use_rtk = false",
            ]
        ),
        encoding="utf-8",
    )


def _disable_optional_cache_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    original_which = _codex.shutil.which

    def which(command: str) -> str | None:
        if command in {"go", "golangci-lint"}:
            return None
        return original_which(command)

    monkeypatch.setattr(_codex.shutil, "which", which)


def test_run_renders_codex_command_and_environment(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable, output = _fake_codex(tmp_path)
    configured_dir = tmp_path / "configured"
    requested_dir = tmp_path / "requested"
    configured_dir.mkdir()
    requested_dir.mkdir()
    config_path = tmp_path / "config.toml"
    configured_home = tmp_path / "configured-home"
    _write_config(config_path, executable, configured_home, configured_dir)
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
    _disable_optional_cache_tools(monkeypatch)

    result = main(
        [
            "--config",
            str(config_path),
            "run",
            "--agent",
            "codex",
            "--worktree-dir",
            str(git_worktree),
            "--add-dir",
            str(requested_dir),
            "--model",
            "run-model",
            "--reasoning-effort",
            "high",
            "--sandbox",
            "workspace-write",
            "--",
            "implement",
            "--",
            "this",
        ]
    )

    assert result == 0
    invocation = json.loads(output.read_text(encoding="utf-8"))
    assert invocation["cwd"] == str(git_worktree)
    assert invocation["codex_home"] == str(configured_home)
    assert invocation["use_rtk"] == "0"
    assert invocation["rust_log"] == "warn"
    assert invocation["argv"][:8] == [
        "--sandbox",
        "workspace-write",
        "--model",
        "run-model",
        "--config",
        'model_reasoning_effort="high"',
        "--add-dir",
        str(configured_dir),
    ]
    assert invocation["argv"][-3:] == ["implement", "--", "this"]
    assert invocation["argv"].index(str(configured_dir)) < invocation["argv"].index(
        str(requested_dir)
    )


def test_run_uses_resume_and_environment_home_precedence(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable, output = _fake_codex(tmp_path)
    writable_dir = tmp_path / "writable"
    writable_dir.mkdir()
    config_path = tmp_path / "config.toml"
    _write_config(config_path, executable, tmp_path / "configured-home", writable_dir)
    environment_home = tmp_path / "environment-home"
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
    monkeypatch.setenv("CODEX_HOME", str(environment_home))
    monkeypatch.setenv("USE_RTK", "caller-value")
    _disable_optional_cache_tools(monkeypatch)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "run",
                "--agent",
                "codex",
                "--worktree-dir",
                str(git_worktree),
                "--session-id",
                "opaque/session",
            ]
        )
        == 0
    )

    invocation = json.loads(output.read_text(encoding="utf-8"))
    assert invocation["argv"][:3] == ["resume", "--sandbox", "read-only"]
    assert invocation["argv"][-1] == "opaque/session"
    assert invocation["codex_home"] == str(environment_home)
    assert invocation["use_rtk"] == "caller-value"


def test_run_propagates_child_exit_status(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable, output = _fake_codex(tmp_path)
    writable_dir = tmp_path / "writable"
    writable_dir.mkdir()
    config_path = tmp_path / "config.toml"
    _write_config(config_path, executable, tmp_path / "home", writable_dir)
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
    monkeypatch.setenv("FAKE_CODEX_EXIT", "17")
    _disable_optional_cache_tools(monkeypatch)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "run",
                "--agent",
                "codex",
                "--worktree-dir",
                str(git_worktree),
                "--fork-session-id",
                "parent",
            ]
        )
        == 17
    )
    assert json.loads(output.read_text(encoding="utf-8"))["argv"][0] == "fork"


def test_run_rejects_missing_explicit_writable_directory(
    git_worktree: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[core]\nwritable_dirs = ["/definitely/missing/launcher-directory"]\n',
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--config",
                str(config_path),
                "run",
                "--agent",
                "codex",
                "--worktree-dir",
                str(git_worktree),
            ]
        )
        == 2
    )
    assert "configured writable directory is not an existing directory" in capsys.readouterr().err


def test_run_rejects_nonexistent_worktree_without_creating_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_worktree = tmp_path / "missing-worktree"

    assert (
        main(
            [
                "run",
                "--agent",
                "codex",
                "--worktree-dir",
                str(missing_worktree),
            ]
        )
        == 2
    )
    assert not missing_worktree.exists()
    assert "worktree is not a directory" in capsys.readouterr().err


def test_run_requires_separator_for_passthrough(git_worktree: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "run",
                "--agent",
                "codex",
                "--worktree-dir",
                str(git_worktree),
                "unexpected",
            ]
        )
