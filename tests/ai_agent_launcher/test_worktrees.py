from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_agent_launcher import _lifecycle
from ai_agent_launcher._launchers import launcher_git_metadata_access, read_launcher
from ai_agent_launcher._models import GitMetadataAccess
from ai_agent_launcher.cli import main


@pytest.fixture(autouse=True)
def _clear_git_index_file(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep nested test repositories independent of a caller's Git index."""
    monkeypatch.delenv("GIT_INDEX_FILE", raising=False)


@pytest.fixture()
def primary_worktree(tmp_path: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "test@example.invalid")
    _git(primary, "config", "user.name", "Launcher Test")
    (primary / "README.md").write_text("initial\n", encoding="utf-8")
    _git(primary, "add", "README.md")
    _git(primary, "commit", "-qm", "initial")
    return primary


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _config(
    path: Path,
    launcher_directory: Path,
    default_git_metadata_access: str = "worktree",
) -> None:
    path.write_text(
        "\n".join(
            (
                "[core]",
                "writable_dirs = []",
                f'launcher_directory = "{launcher_directory}"',
                f'default_git_metadata_access = "{default_git_metadata_access}"',
            )
        ),
        encoding="utf-8",
    )


def _create_source_worktree(primary: Path, name: str = "source") -> Path:
    source = primary.parent / name
    _git(primary, "worktree", "add", "-b", "feature/source", str(source), "HEAD")
    return source


def test_new_uses_primary_head_by_default_and_accepts_explicit_start_ref(
    primary_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _create_source_worktree(primary_worktree)
    source_head = _git(source, "rev-parse", "HEAD")
    (primary_worktree / "README.md").write_text("primary update\n", encoding="utf-8")
    _git(primary_worktree, "commit", "-am", "primary update")
    primary_head = _git(primary_worktree, "rev-parse", "HEAD")
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory, "shared")
    preparation = tmp_path / "prepare"
    prepared = tmp_path / "prepared"
    local_directory = tmp_path / "local"
    local_directory.mkdir()
    preparation.write_text('#!/bin/sh\nprintf "%s" "$2" > "$PREPARED_OUTPUT"\n', encoding="utf-8")
    preparation.chmod(0o755)
    monkeypatch.setenv("PREPARED_OUTPUT", str(prepared))
    monkeypatch.chdir(source)

    default_target = tmp_path / "new-default"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(default_target),
                "--branch",
                "feature/new-default",
                "--marker",
                "# generated launcher",
                "--prepare",
                str(preparation),
                "--add-dir",
                str(local_directory),
            ]
        )
        == 0
    )
    assert _git(default_target, "rev-parse", "HEAD") == primary_head
    assert prepared.read_text(encoding="utf-8") == str(default_target)
    metadata = read_launcher(launcher_directory / "codex-new-default")
    assert metadata.session is None
    assert metadata.local_writable_dirs == (local_directory.resolve(),)
    assert launcher_git_metadata_access(metadata) is GitMetadataAccess.SHARED
    assert "default session: none" in capsys.readouterr().out

    explicit_target = tmp_path / "new-explicit"
    explicit_launcher = tmp_path / "custom-launcher"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(explicit_target),
                "--from",
                "feature/source",
                "--launcher",
                str(explicit_launcher),
                "--marker",
                "# generated launcher",
                "--git-metadata-access",
                "worktree",
            ]
        )
        == 0
    )
    assert _git(explicit_target, "rev-parse", "HEAD") == source_head
    assert explicit_launcher.is_file()
    assert (
        launcher_git_metadata_access(read_launcher(explicit_launcher)) is GitMetadataAccess.WORKTREE
    )


def test_stack_derives_strict_sibling_targets_from_committed_source_head(
    primary_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _create_source_worktree(primary_worktree)
    committed_head = _git(source, "rev-parse", "HEAD")
    (source / "README.md").write_text("uncommitted\n", encoding="utf-8")
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory)
    local_directory = tmp_path / "local"
    local_directory.mkdir()
    monkeypatch.chdir(source)

    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "stack",
                "--agent",
                "codex",
                "--suffix",
                "-child",
                "--marker",
                "# generated launcher",
                "--add-dir",
                str(local_directory),
            ]
        )
        == 0
    )

    target = source.parent / "source-child"
    assert _git(target, "branch", "--show-current") == "feature/source-child"
    assert _git(target, "rev-parse", "HEAD") == committed_head
    assert "uncommitted" not in (target / "README.md").read_text(encoding="utf-8")
    metadata = read_launcher(launcher_directory / "codex-source-child")
    assert metadata.session is None
    assert metadata.local_writable_dirs == (local_directory.resolve(),)


def test_new_rejects_collisions_without_creating_resources(
    primary_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory)
    monkeypatch.chdir(primary_worktree)

    occupied_target = tmp_path / "occupied"
    occupied_target.mkdir()
    sentinel = occupied_target / "sentinel"
    sentinel.write_text("preserve\n", encoding="utf-8")
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(occupied_target),
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert "worktree path already exists" in capsys.readouterr().err

    _git(primary_worktree, "branch", "feature/occupied-branch")
    branch_target = tmp_path / "occupied-branch"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(branch_target),
                "--branch",
                "feature/occupied-branch",
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert not branch_target.exists()

    launcher_directory.mkdir()
    occupied_launcher = launcher_directory / "codex-occupied-launcher"
    occupied_launcher.write_text("preserve\n", encoding="utf-8")
    launcher_target = tmp_path / "occupied-launcher"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(launcher_target),
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert not launcher_target.exists()
    assert occupied_launcher.read_text(encoding="utf-8") == "preserve\n"

    symlink_launcher = launcher_directory / "codex-symlink-launcher"
    symlink_launcher.symlink_to(tmp_path / "missing-launcher")
    symlink_target = tmp_path / "symlink-launcher"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(symlink_target),
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert symlink_launcher.is_symlink()
    assert not symlink_target.exists()


def test_stack_rejects_unsafe_suffix_and_detached_source(
    primary_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _create_source_worktree(primary_worktree)
    config = tmp_path / "config.toml"
    _config(config, tmp_path / "launchers")
    monkeypatch.chdir(source)

    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "stack",
                "--agent",
                "codex",
                "--suffix",
                "/unsafe",
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert "single path-name fragment" in capsys.readouterr().err

    _git(source, "switch", "--detach", "-q")
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "stack",
                "--agent",
                "codex",
                "--suffix",
                "-detached",
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert "attached source branch" in capsys.readouterr().err
    assert not (source.parent / "source-detached").exists()


def test_new_rejects_invalid_start_ref_before_creating_targets(
    primary_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.toml"
    _config(config, tmp_path / "launchers")
    target = tmp_path / "missing-ref"
    monkeypatch.chdir(primary_worktree)

    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(target),
                "--branch",
                "feature/missing-ref",
                "--from",
                "not-a-ref",
                "--marker",
                "# generated launcher",
            ]
        )
        == 2
    )
    assert not target.exists()
    assert _git(primary_worktree, "branch", "--list", "feature/missing-ref") == ""


def test_new_rolls_back_owned_resources_and_preserves_external_launcher(
    primary_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory)
    monkeypatch.chdir(primary_worktree)
    failing_preparation = tmp_path / "fail-prepare"
    failing_preparation.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    failing_preparation.chmod(0o755)
    failed_target = tmp_path / "failed-prepare"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(failed_target),
                "--branch",
                "feature/failed-prepare",
                "--marker",
                "# generated launcher",
                "--prepare",
                str(failing_preparation),
            ]
        )
        == 2
    )
    assert not failed_target.exists()
    assert _git(primary_worktree, "branch", "--list", "feature/failed-prepare") == ""

    external_launcher = launcher_directory / "codex-failed-render"
    creating_preparation = tmp_path / "create-launcher"
    creating_preparation.write_text(
        '#!/bin/sh\nmkdir -p "$(dirname "$EXTERNAL_LAUNCHER")"\ntouch "$EXTERNAL_LAUNCHER"\n',
        encoding="utf-8",
    )
    creating_preparation.chmod(0o755)
    monkeypatch.setenv("EXTERNAL_LAUNCHER", str(external_launcher))
    render_target = tmp_path / "failed-render"
    assert (
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(render_target),
                "--branch",
                "feature/failed-render",
                "--marker",
                "# generated launcher",
                "--prepare",
                str(creating_preparation),
            ]
        )
        == 2
    )
    assert not render_target.exists()
    assert _git(primary_worktree, "branch", "--list", "feature/failed-render") == ""
    assert external_launcher.is_file()


def test_new_rolls_back_owned_resources_after_unexpected_launcher_failure(
    primary_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory)
    monkeypatch.chdir(primary_worktree)

    def fail_prepare(
        _self: _lifecycle.LauncherLifecycle,
        _worktree_dir: Path,
        _preparation_path: Path | None,
    ) -> None:
        raise RuntimeError("unexpected launcher preparation failure")

    monkeypatch.setattr(_lifecycle.LauncherLifecycle, "prepare", fail_prepare)
    target = tmp_path / "unexpected-failure"

    with pytest.raises(RuntimeError, match="unexpected launcher preparation failure"):
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(target),
                "--branch",
                "feature/unexpected-failure",
                "--marker",
                "# generated launcher",
            ]
        )

    assert not target.exists()
    assert _git(primary_worktree, "branch", "--list", "feature/unexpected-failure") == ""


def test_new_rolls_back_owned_resources_after_interruption(
    primary_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher_directory = tmp_path / "launchers"
    config = tmp_path / "config.toml"
    _config(config, launcher_directory)
    monkeypatch.chdir(primary_worktree)

    def interrupt_prepare(
        _self: _lifecycle.LauncherLifecycle,
        _worktree_dir: Path,
        _preparation_path: Path | None,
    ) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(_lifecycle.LauncherLifecycle, "prepare", interrupt_prepare)
    target = tmp_path / "interrupted"

    with pytest.raises(KeyboardInterrupt):
        main(
            [
                "--config",
                str(config),
                "worktree",
                "new",
                "--agent",
                "codex",
                "--worktree-dir",
                str(target),
                "--branch",
                "feature/interrupted",
                "--marker",
                "# generated launcher",
            ]
        )

    assert not target.exists()
    assert _git(primary_worktree, "branch", "--list", "feature/interrupted") == ""
