from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ai_agent_launcher import _codex, _launchers
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import (
    atomic_text_write,
    build_metadata,
    launcher_git_metadata_access,
    read_launcher,
    read_launcher_artifact,
    replace_session,
    with_metadata_extension,
    write_launcher,
)
from ai_agent_launcher._models import AgentId, GitMetadataAccess
from ai_agent_launcher._runtime import RunContext
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


def _config(path: Path, executable: Path, home: Path, sandbox: str = "workspace-write") -> None:
    path.write_text(
        "\n".join(
            (
                "[core]",
                "writable_dirs = []",
                "",
                "[agents.codex]",
                f'executable = "{executable}"',
                f'home = "{home}"',
                f'sandbox = "{sandbox}"',
                "use_rtk = false",
            )
        ),
        encoding="utf-8",
    )


def test_atomic_text_write_removes_temporary_file_after_replace_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "launcher"

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("forced replacement failure")

    monkeypatch.setattr(_launchers.os, "replace", fail_replace)

    with pytest.raises(LauncherError, match="unable to write"):
        atomic_text_write(target, "#!/bin/sh\n", 0o700)

    assert not target.exists()
    assert list(tmp_path.glob(".launcher.*")) == []


def test_atomic_text_write_removes_temporary_file_after_encoding_failure(tmp_path: Path) -> None:
    target = tmp_path / "launcher"

    with pytest.raises(LauncherError, match="unable to write"):
        atomic_text_write(target, "\ud800", 0o700)

    assert not target.exists()
    assert list(tmp_path.glob(".launcher.*")) == []


def test_launcher_run_and_fork_report_unknown_adapter(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    metadata = build_metadata(AgentId("other"), git_worktree, None, ())
    write_launcher(source, replace_session(metadata, "parent-session"))

    assert main(["launcher", "run", "--launcher", str(source)]) == 2
    assert "unknown agent identifier other" in capsys.readouterr().err

    assert (
        main(
            [
                "launcher",
                "fork",
                "--launcher",
                str(source),
                "--target-launcher",
                str(target),
            ]
        )
        == 2
    )
    assert "unknown agent identifier other" in capsys.readouterr().err
    assert not target.exists()


def test_create_and_pin_preserve_versioned_metadata(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
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
                "--add-dir",
                str(local_dir),
            ]
        )
        == 0
    )
    assert launcher.stat().st_mode & 0o777 == 0o700
    content = launcher.read_text(encoding="utf-8")
    assert 'exec ai-agent-launcher launcher run --launcher "$launcher_path" -- "$@"' in content
    assert (
        "# Inspect metadata with: ai-agent-launcher launcher describe "
        "--launcher <launcher-path>" in content
    )
    assert read_launcher(launcher).session is None
    artifact = read_launcher_artifact(launcher)
    metadata_line = next(
        line
        for line in content.splitlines()
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    encoded = metadata_line.removeprefix("# ai-agent-launcher-metadata-v1: ")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert "marker" not in payload
    assert artifact.extensions == {"core": {"git_metadata_access": "worktree"}}
    assert launcher_git_metadata_access(artifact) is GitMetadataAccess.WORKTREE

    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 0
    assert "session: unpinned" in capsys.readouterr().out

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


def test_legacy_marker_metadata_is_ignored_and_dropped_when_rewritten(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
            ]
        )
        == 0
    )

    lines = launcher.read_text(encoding="utf-8").splitlines()
    metadata_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    encoded = lines[metadata_index].removeprefix("# ai-agent-launcher-metadata-v1: ")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["marker"] = {"legacy": ["ignored", True]}
    replacement = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    lines.insert(2, "# legacy marker")
    lines[metadata_index + 1] = f"# ai-agent-launcher-metadata-v1: {replacement}"
    launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert read_launcher(launcher).session is None
    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 0
    assert "marker:" not in capsys.readouterr().out

    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "one"]) == 0
    rewritten = launcher.read_text(encoding="utf-8")
    assert "# legacy marker" not in rewritten
    rewritten_line = next(
        line
        for line in rewritten.splitlines()
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    rewritten_encoded = rewritten_line.removeprefix("# ai-agent-launcher-metadata-v1: ")
    rewritten_payload = json.loads(
        base64.urlsafe_b64decode(rewritten_encoded + "=" * (-len(rewritten_encoded) % 4))
    )
    assert "marker" not in rewritten_payload
    rewritten_metadata = read_launcher_artifact(launcher)
    assert rewritten_metadata.session is not None
    assert rewritten_metadata.session.value == "one"


def test_launcher_metadata_rejects_unknown_v1_key(git_worktree: Path, tmp_path: Path) -> None:
    launcher = tmp_path / "launcher"
    payload: dict[str, object] = {
        "agent_id": "codex",
        "format_version": 1,
        "local_writable_dirs": [],
        "preparation_path": None,
        "session_id": None,
        "unexpected": True,
        "worktree_dir": str(git_worktree),
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    launcher.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                f"# ai-agent-launcher-metadata-v1: {encoded}",
                "",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(LauncherError, match="unsupported launcher metadata version"):
        read_launcher_artifact(launcher)


def test_launcher_sandbox_updates_persisted_mode_and_directories(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executable = _fake_codex(tmp_path)
    output = tmp_path / "output.json"
    config_path = tmp_path / "config.toml"
    _config(config_path, executable, tmp_path / "home", sandbox="read-only")
    inherited = tmp_path / "inherited"
    added = tmp_path / "added"
    removed = tmp_path / "removed"
    inherited.mkdir()
    added.mkdir()
    removed.mkdir()
    launcher = tmp_path / "launcher"
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
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
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
                "--add-dir",
                str(inherited),
                "--add-dir",
                str(removed),
            ]
        )
        == 0
    )
    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "parent"]) == 0
    metadata = with_metadata_extension(read_launcher(launcher), "custom", "enabled", True)
    write_launcher(launcher, metadata, replace=True, mode=0o750)

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--mode",
                "workspace-write",
                "--add-dir",
                str(inherited),
                "--add-dir",
                str(added),
                "--remove-dir",
                str(removed),
            ]
        )
        == 0
    )

    updated = read_launcher(launcher)
    assert updated.session is not None
    assert updated.session.value == "parent"
    assert updated.local_writable_dirs == (inherited.resolve(), added.resolve())
    assert updated.extensions == {
        "codex": {"sandbox": "workspace-write"},
        "core": {"git_metadata_access": "worktree"},
        "custom": {"enabled": True},
    }
    assert launcher.stat().st_mode & 0o777 == 0o750

    assert main(["--config", str(config_path), "launcher", "run", "--launcher", str(launcher)]) == 0
    invocation = json.loads(output.read_text(encoding="utf-8"))
    assert invocation[:3] == ["resume", "--sandbox", "workspace-write"]
    assert str(removed.resolve()) not in invocation
    assert invocation[-1] == "parent"

    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 0
    assert '  - codex.sandbox: "workspace-write"' in capsys.readouterr().out


def test_launcher_sandbox_directory_update_retains_configured_mode(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = _fake_codex(tmp_path)
    output = tmp_path / "output.json"
    config_path = tmp_path / "config.toml"
    _config(config_path, executable, tmp_path / "home", sandbox="read-only")
    added = tmp_path / "added"
    added.mkdir()
    launcher = tmp_path / "launcher"
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
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
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--add-dir",
                str(added),
            ]
        )
        == 0
    )
    assert read_launcher(launcher).extensions == {"core": {"git_metadata_access": "worktree"}}

    assert main(["--config", str(config_path), "launcher", "run", "--launcher", str(launcher)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))[:3] == [
        "--sandbox",
        "read-only",
        "--add-dir",
    ]


def test_launcher_sandbox_removes_stale_local_directories(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
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
                "--add-dir",
                str(first),
                "--add-dir",
                str(second),
            ]
        )
        == 0
    )
    first.rmdir()
    second.rmdir()

    with pytest.raises(LauncherError, match="launcher metadata is invalid"):
        read_launcher(launcher)

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--remove-dir",
                str(first),
                "--remove-dir",
                str(second),
            ]
        )
        == 0
    )
    assert read_launcher(launcher).local_writable_dirs == ()


def test_launcher_sandbox_does_not_rewrite_for_unstored_removal(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    launcher = tmp_path / "launcher"
    missing = tmp_path / "missing"
    added = tmp_path / "added"
    added.mkdir()
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
            ]
        )
        == 0
    )
    original = launcher.read_bytes()

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--remove-dir",
                str(missing),
            ]
        )
        == 0
    )
    assert launcher.read_bytes() == original
    assert capsys.readouterr().err == (
        f"warning: launcher-local writable directory is not stored: {missing.resolve()}\n"
    )

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--add-dir",
                str(added),
                "--remove-dir",
                str(missing),
            ]
        )
        == 0
    )
    assert read_launcher(launcher).local_writable_dirs == (added.resolve(),)
    assert capsys.readouterr().err == (
        f"warning: launcher-local writable directory is not stored: {missing.resolve()}\n"
    )


def test_launcher_sandbox_rejects_invalid_directory_updates_without_rewriting(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    launcher = tmp_path / "launcher"
    directory = tmp_path / "directory"
    directory.mkdir()
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
            ]
        )
        == 0
    )
    original = launcher.read_bytes()

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--add-dir",
                str(directory),
                "--remove-dir",
                str(directory),
            ]
        )
        == 2
    )
    assert launcher.read_bytes() == original
    capsys.readouterr()

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--remove-dir",
                "~missing-user/path",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert (
        "launcher local directory removal is not an absolute path: ~missing-user/path"
        in captured.err
    )
    assert "Traceback" not in captured.err
    assert launcher.read_bytes() == original


def test_launcher_sandbox_preserves_invalid_stale_entries_not_removed(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    removed = tmp_path / "removed"
    retained = tmp_path / "retained"
    removed.mkdir()
    retained.mkdir()
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
                "--add-dir",
                str(removed),
                "--add-dir",
                str(retained),
            ]
        )
        == 0
    )
    removed.rmdir()
    retained.rmdir()
    original = launcher.read_bytes()

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--remove-dir",
                str(removed),
            ]
        )
        == 2
    )
    assert launcher.read_bytes() == original


def test_launcher_sandbox_rejects_empty_or_invalid_updates_without_rewriting(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
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
            ]
        )
        == 0
    )
    original = launcher.read_bytes()

    with pytest.raises(SystemExit, match="2"):
        main(["launcher", "sandbox", "--launcher", str(launcher)])
    assert launcher.read_bytes() == original

    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--mode",
                "not-a-sandbox-mode",
            ]
        )
    assert launcher.read_bytes() == original

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--add-dir",
                str(tmp_path / "missing"),
            ]
        )
        == 2
    )
    assert launcher.read_bytes() == original

    assert (
        main(
            [
                "launcher",
                "sandbox",
                "--launcher",
                str(launcher),
                "--remove-dir",
                "relative",
            ]
        )
        == 2
    )
    assert launcher.read_bytes() == original


def test_describe_reports_effective_dirs_and_degrades(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher = tmp_path / "launcher"
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    configured_dir = tmp_path / "configured"
    configured_dir.mkdir()
    (git_worktree / ".context").mkdir()
    preparation = tmp_path / "prepare"
    prepared = tmp_path / "prepared"
    preparation.write_text(f'#!/bin/sh\nprintf prepared > "{prepared}"\n', encoding="utf-8")
    preparation.chmod(0o755)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            (
                "[core]",
                f"writable_dirs = [{json.dumps(str(configured_dir))}]",
            )
        ),
        encoding="utf-8",
    )
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
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
                "--prepare",
                str(preparation),
                "--add-dir",
                str(local_dir),
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
                str(launcher),
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
                "describe",
                "--launcher",
                str(launcher),
            ]
        )
        == 0
    )
    assert prepared.exists() is False
    assert capsys.readouterr().out == "\n".join(
        (
            f"launcher: {launcher}",
            "format version: 1",
            "agent: codex",
            f"worktree: {git_worktree.resolve()}",
            "session: parent-session",
            f"preparation: {preparation.resolve()}",
            "git metadata access: worktree",
            "metadata extensions:",
            '  - core.git_metadata_access: "worktree"',
            "local writable directories:",
            f"  - {local_dir.resolve()}",
            "effective writable directories:",
            f"  - {configured_dir.resolve()}",
            f"  - {local_dir.resolve()}",
            f"  - {(git_worktree / '.context').resolve()}",
            f"  - {(git_worktree / '.git').resolve()}",
            "",
        )
    )

    preparation.unlink()
    local_dir.rmdir()
    configured_dir.rmdir()
    shutil.rmtree(git_worktree)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "launcher",
                "describe",
                "--launcher",
                str(launcher),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert f"worktree: {git_worktree.resolve()}" in output
    assert "effective writable directories: none" in output
    assert "configured writable directory is not an existing directory" in output
    assert "--add-dir is not an existing directory" in output
    with pytest.raises(LauncherError, match="launcher metadata is invalid"):
        read_launcher(launcher)


def test_launcher_create_uses_configured_or_explicit_git_metadata_access(
    git_worktree: Path, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[core]\ndefault_git_metadata_access = "shared"\n', encoding="utf-8")
    configured = tmp_path / "configured"
    explicit = tmp_path / "explicit"

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
                str(configured),
                "--worktree-dir",
                str(git_worktree),
            ]
        )
        == 0
    )
    assert launcher_git_metadata_access(read_launcher(configured)) is GitMetadataAccess.SHARED

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
                str(explicit),
                "--worktree-dir",
                str(git_worktree),
                "--git-metadata-access",
                "worktree",
            ]
        )
        == 0
    )
    assert launcher_git_metadata_access(read_launcher(explicit)) is GitMetadataAccess.WORKTREE


def test_legacy_launcher_uses_implicit_worktree_access_without_rewrite(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
            ]
        )
        == 0
    )
    lines = launcher.read_text(encoding="utf-8").splitlines()
    metadata_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    encoded = lines[metadata_index].removeprefix("# ai-agent-launcher-metadata-v1: ")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    del payload["extensions"]
    replacement = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    lines[metadata_index] = f"# ai-agent-launcher-metadata-v1: {replacement}"
    legacy_content = "\n".join(lines) + "\n"
    launcher.write_text(legacy_content, encoding="utf-8")

    assert (
        launcher_git_metadata_access(read_launcher_artifact(launcher)) is GitMetadataAccess.WORKTREE
    )
    assert launcher.read_text(encoding="utf-8") == legacy_content
    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 0
    assert "git metadata access: worktree (default)" in capsys.readouterr().out
    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "one"]) == 0

    lines = launcher.read_text(encoding="utf-8").splitlines()
    encoded = next(
        line.removeprefix("# ai-agent-launcher-metadata-v1: ")
        for line in lines
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    pinned_payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert "extensions" not in pinned_payload


def test_pin_preserves_unknown_metadata_extensions(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
            ]
        )
        == 0
    )
    lines = launcher.read_text(encoding="utf-8").splitlines()
    metadata_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    encoded = lines[metadata_index].removeprefix("# ai-agent-launcher-metadata-v1: ")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["extensions"] = {"custom": {"enabled": True}}
    replacement = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    lines[metadata_index] = f"# ai-agent-launcher-metadata-v1: {replacement}"
    launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["launcher", "pin", "--launcher", str(launcher), "--session-id", "one"]) == 0
    artifact = read_launcher_artifact(launcher)
    assert artifact.extensions == {"custom": {"enabled": True}}
    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 0
    assert "  - custom.enabled: true" in capsys.readouterr().out


def test_describe_degrades_when_configuration_is_unavailable(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    launcher = tmp_path / "launcher"
    missing_config = tmp_path / "missing-config.toml"
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
            ]
        )
        == 0
    )

    assert (
        main(
            [
                "--config",
                str(missing_config),
                "launcher",
                "describe",
                "--launcher",
                str(launcher),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "effective writable directories: none" in output
    assert "configuration file does not exist" in output


def test_describe_sorts_local_and_effective_writable_directories(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher = tmp_path / "launcher"
    configured_a = tmp_path / "configured-a"
    configured_z = tmp_path / "configured-z"
    local_a = tmp_path / "local-a"
    local_z = tmp_path / "local-z"
    for directory in (configured_a, configured_z, local_a, local_z):
        directory.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            (
                "[core]",
                "writable_dirs = ["
                f"{json.dumps(str(configured_z))}, {json.dumps(str(configured_a))}]",
            )
        ),
        encoding="utf-8",
    )
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
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
                "--add-dir",
                str(local_z),
                "--add-dir",
                str(local_a),
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
                "describe",
                "--launcher",
                str(launcher),
            ]
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    local_start = lines.index("local writable directories:") + 1
    effective_start = lines.index("effective writable directories:")
    assert lines[local_start:effective_start] == [
        f"  - {local_a.resolve()}",
        f"  - {local_z.resolve()}",
    ]
    assert lines[effective_start + 1 :] == sorted(lines[effective_start + 1 :])


def test_effective_directory_resolution_does_not_create_go_caches(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    go_cache = tmp_path / "go-cache"
    go_module_cache = tmp_path / "go-module-cache"
    adapter = _codex.CodexAdapter()

    def which(command: str) -> str | None:
        return "/test/go" if command == "go" else None

    def go_environment(
        _self: _codex.CodexAdapter,
        _executable: str,
        variable: str,
        _worktree: Path,
    ) -> str:
        return str(go_cache if variable == "GOCACHE" else go_module_cache)

    monkeypatch.setattr(_codex.shutil, "which", which)
    monkeypatch.setattr(_codex.CodexAdapter, "_go_environment", go_environment)

    report = adapter.resolve_writable_dirs(
        RunContext(git_worktree, (), (), ()),
        {},
    )

    assert go_cache in report.directories
    assert go_module_cache in report.directories
    assert go_cache.exists() is False
    assert go_module_cache.exists() is False


def test_writable_directory_resolution_skips_disabled_go_caches(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _codex.CodexAdapter()

    def which(command: str) -> str | None:
        return "/test/go" if command == "go" else None

    def go_environment(
        _self: _codex.CodexAdapter,
        _executable: str,
        _variable: str,
        _worktree: Path,
    ) -> str:
        return "off"

    monkeypatch.setattr(_codex.shutil, "which", which)
    monkeypatch.setattr(_codex.CodexAdapter, "_go_environment", go_environment)
    context = RunContext(git_worktree, (), (), ())

    report = adapter.resolve_writable_dirs(context, {})

    assert report.notes == ()
    assert adapter._writable_dirs(context) == report.directories


def test_describe_rejects_unsupported_metadata_version(
    git_worktree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
            ]
        )
        == 0
    )
    lines = launcher.read_text(encoding="utf-8").splitlines()
    metadata_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("# ai-agent-launcher-metadata-v1: ")
    )
    encoded = lines[metadata_index].removeprefix("# ai-agent-launcher-metadata-v1: ")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["format_version"] = 2
    replacement = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    lines[metadata_index] = f"# ai-agent-launcher-metadata-v1: {replacement}"
    launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unsupported launcher metadata version" in captured.err


def test_describe_rejects_non_generated_launcher(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    launcher = tmp_path / "launcher"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")

    assert main(["launcher", "describe", "--launcher", str(launcher)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not a supported generated launcher" in captured.err


def test_generated_shim_delegates_through_path(git_worktree: Path, tmp_path: Path) -> None:
    launcher = tmp_path / "launcher"
    capture = tmp_path / "capture"
    working_directory = tmp_path / "working-directory"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "ai-agent-launcher"
    command.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" > "$LAUNCHER_CAPTURE"\n'
        'printf \'%s\\n\' "$PWD" > "$LAUNCHER_WORKING_DIRECTORY"\n',
        encoding="utf-8",
    )
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
            ]
        )
        == 0
    )

    environment = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LAUNCHER_CAPTURE": str(capture),
        "LAUNCHER_WORKING_DIRECTORY": str(working_directory),
    }
    subprocess.run(
        ["/bin/sh", f"./{launcher.name}", "continue"],
        check=True,
        cwd=launcher.parent,
        env=environment,
    )

    assert capture.read_text(encoding="utf-8").splitlines() == [
        "launcher",
        "run",
        "--launcher",
        str(launcher),
        "--",
        "continue",
    ]
    assert working_directory.read_text(encoding="utf-8").strip() == str(git_worktree)


def test_run_uses_pinned_session_through_codex_adapter(
    git_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = _fake_codex(tmp_path)
    config_path = tmp_path / "config.toml"
    home = tmp_path / "codex-home"
    _config(config_path, executable, home)
    launcher = tmp_path / "launcher"
    output = tmp_path / "fake-codex.json"
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("FAKE_CODEX_OUTPUT", str(output))
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
                str(launcher),
                "--worktree-dir",
                str(git_worktree),
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
                str(launcher),
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
                "run",
                "--launcher",
                str(launcher),
                "--",
                "continue",
            ]
        )
        == 0
    )

    assert json.loads(output.read_text(encoding="utf-8"))[-2:] == ["parent-session", "continue"]


def test_fork_prepares_worktree_and_creates_child_launcher(
    git_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executable = _fake_codex(tmp_path)
    config_path = tmp_path / "config.toml"
    home = tmp_path / "codex-home"
    _config(config_path, executable, home)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    inherited = tmp_path / "inherited"
    added = tmp_path / "added"
    removed = tmp_path / "removed"
    unstored = tmp_path / "unstored"
    inherited.mkdir()
    added.mkdir()
    removed.mkdir()
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
                "--prepare",
                str(preparation),
                "--add-dir",
                str(inherited),
                "--add-dir",
                str(removed),
                "--sandbox-mode",
                "read-only",
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
                "--remove-dir",
                str(removed),
                "--remove-dir",
                str(unstored),
                "--sandbox-mode",
                "danger-full-access",
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
    assert target_metadata.extensions == {
        "codex": {"sandbox": "danger-full-access"},
        "core": {"git_metadata_access": "worktree"},
    }
    assert read_launcher(source).local_writable_dirs == (inherited.resolve(), removed.resolve())
    assert read_launcher(source).extensions == {
        "codex": {"sandbox": "read-only"},
        "core": {"git_metadata_access": "worktree"},
    }
    assert capsys.readouterr().err == (
        f"warning: launcher-local writable directory is not stored: {unstored.resolve()}\n"
    )


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
    inherited = tmp_path / "inherited"
    added = tmp_path / "added"
    removed = tmp_path / "removed"
    inherited.mkdir()
    added.mkdir()
    removed.mkdir()
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
                "--add-dir",
                str(inherited),
                "--add-dir",
                str(removed),
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
                "--add-dir",
                str(added),
                "--remove-dir",
                str(removed),
                "--sandbox-mode",
                "read-only",
            ]
        )
        == 0
    )
    assert "unrelated-parent" in capsys.readouterr().out
    target_metadata = read_launcher(target)
    assert target_metadata.session is not None
    assert target_metadata.session.value == "existing-session"
    assert target_metadata.local_writable_dirs == (inherited.resolve(), added.resolve())
    assert target_metadata.extensions == {
        "codex": {"sandbox": "read-only"},
        "core": {"git_metadata_access": "worktree"},
    }
    assert read_launcher(source).local_writable_dirs == (inherited.resolve(), removed.resolve())
