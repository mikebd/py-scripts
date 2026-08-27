from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest


def _release_lock_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "dx" / "lock_release.py"
    specification = importlib.util.spec_from_file_location("lock_release", script)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _run(arguments: list[str], root: Path) -> str:
    result = subprocess.run(arguments, capture_output=True, check=True, cwd=root, text=True)
    return result.stdout


def _write_fixture_files(root: Path) -> None:
    (root / "docs" / "ai-agent-launcher").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        """[project]
name = "example-project"
version = "0.1.2"
""",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        """version = 1

[[package]]
name = "example-project"
version = "0.1.2"
""",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        """# Changelog

## [v0.1.3] - Draft

### Scope

- `example`

### Added

- A pending release.
""",
        encoding="utf-8",
    )
    (root / "docs" / "ai-agent-launcher" / "README.md").write_text(
        """# Example

<!-- release-lock: current-version-examples:start -->

Install `example-project@v0.1.2`.

<!-- release-lock: current-version-examples:end -->
""",
        encoding="utf-8",
    )
    (root / "unexpected.txt").write_text("unchanged\n", encoding="utf-8")


def _source_repository(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _run(["git", "init", "-q"], root)
    _run(["git", "config", "user.email", "tests@example.invalid"], root)
    _run(["git", "config", "user.name", "Release Lock Tests"], root)
    _write_fixture_files(root)
    _run(["git", "add", "."], root)
    _run(["git", "commit", "-qm", "initial"], root)
    return root


def _fake_uv(tmp_path: Path) -> Path:
    script = tmp_path / "uv"
    script.write_text(
        f"""#!{sys.executable}
from pathlib import Path
import re
import sys

if sys.argv[1:] != ["lock", "--offline"]:
    raise SystemExit(2)
root = Path.cwd()
version = re.search(r'version = "([^"]+)"', (root / "pyproject.toml").read_text()).group(1)
(root / "uv.lock").write_text(
    'version = 1\\n\\n[[package]]\\nname = "example-project"\\nversion = "' + version + '"\\n'
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _fake_make(tmp_path: Path) -> Path:
    directory = tmp_path / "bin"
    directory.mkdir()
    script = directory / "make"
    script.write_text(
        f"""#!{sys.executable}
import os
from pathlib import Path
import sys

if sys.argv[1:] != ["release-check"]:
    raise SystemExit(2)
if os.environ.get("LOCK_RELEASE_MUTATE") == "1":
    (Path.cwd() / "unexpected.txt").write_text("changed\\n")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return directory


def _with_remote(root: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "-q", str(remote)], root)
    _run(["git", "remote", "add", "origin", str(remote)], root)
    _run(["git", "push", "-qu", "origin", "HEAD"], root)
    return remote


def _branch_reference(root: Path) -> str:
    return f"refs/heads/{_run(['git', 'branch', '--show-current'], root).strip()}"


def _push_branch(root: Path, destination: Path) -> None:
    _run(["git", "push", "-q", str(destination), f"HEAD:{_branch_reference(root)}"], root)


def _bare_head(root: Path, destination: Path) -> str:
    return _run(["git", "--git-dir", str(destination), "rev-parse", _branch_reference(root)], root)


def _with_push_destinations(
    root: Path, tmp_path: Path, count: int
) -> tuple[Path, tuple[Path, ...]]:
    fetch_destination = tmp_path / "fetch.git"
    _run(["git", "init", "--bare", "-q", str(fetch_destination)], root)
    _run(["git", "remote", "add", "origin", str(fetch_destination)], root)
    _push_branch(root, fetch_destination)
    destinations: list[Path] = []
    for index in range(count):
        destination = tmp_path / f"push-{index}.git"
        _run(["git", "init", "--bare", "-q", str(destination)], root)
        _push_branch(root, destination)
        _run(["git", "config", "--add", "remote.origin.pushurl", str(destination)], root)
        destinations.append(destination)
    return fetch_destination, tuple(destinations)


def test_lock_release_finalizes_and_pushes_the_one_commit_ahead_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    remote = _with_remote(root, tmp_path)
    make_directory = _fake_make(tmp_path)
    monkeypatch.setenv("PATH", f"{make_directory}:{os.environ['PATH']}")

    release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))

    assert 'version = "0.1.3"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.3"' in (root / "uv.lock").read_text(encoding="utf-8")
    assert "## [v0.1.3] - 2026-08-27" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "v0.1.3" in (root / "docs" / "ai-agent-launcher" / "README.md").read_text(
        encoding="utf-8"
    )
    assert _run(["git", "status", "--porcelain"], root) == ""
    assert _run(["git", "log", "-1", "--format=%s"], root) == "chore(release): lock v0.1.3\n"
    branch = _run(["git", "branch", "--show-current"], root).strip()
    assert _run(["git", "rev-parse", "HEAD"], root) == _run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{branch}"], root
    )


def test_lock_release_pushes_every_safe_configured_push_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    _, destinations = _with_push_destinations(root, tmp_path, 2)
    make_directory = _fake_make(tmp_path)
    monkeypatch.setenv("PATH", f"{make_directory}:{os.environ['PATH']}")

    release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))

    head = _run(["git", "rev-parse", "HEAD"], root)
    assert tuple(_bare_head(root, destination) for destination in destinations) == (head, head)


def test_lock_release_does_not_push_any_destination_when_one_pushurl_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    fetch_destination, (safe_destination, stale_destination) = _with_push_destinations(
        root, tmp_path, 2
    )
    stale_head = _bare_head(root, stale_destination)
    _run(["git", "commit", "--allow-empty", "-qm", "another local commit"], root)
    safe_head = _run(["git", "rev-parse", "HEAD"], root)
    _push_branch(root, fetch_destination)
    _push_branch(root, safe_destination)
    make_directory = _fake_make(tmp_path)
    monkeypatch.setenv("PATH", f"{make_directory}:{os.environ['PATH']}")

    release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))

    assert "not pushing origin" in capsys.readouterr().out
    assert _bare_head(root, fetch_destination) == safe_head
    assert _bare_head(root, safe_destination) == safe_head
    assert _bare_head(root, stale_destination) == stale_head


def test_lock_release_requires_a_clean_worktree(tmp_path: Path) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(release_lock.ReleaseLockError, match="clean Git worktree"):
        release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))


def test_lock_release_rejects_mismatched_documentation_before_writing(
    tmp_path: Path,
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    documentation = root / "docs" / "ai-agent-launcher" / "README.md"
    documentation.write_text(documentation.read_text(encoding="utf-8").replace("v0.1.2", "v0.1.1"))
    _run(["git", "add", "docs/ai-agent-launcher/README.md"], root)
    _run(["git", "commit", "-qm", "mismatched documentation"], root)

    with pytest.raises(release_lock.ReleaseLockError, match="must match project.version"):
        release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))

    assert 'version = "0.1.2"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "## [v0.1.3] - Draft" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _run(["git", "status", "--porcelain"], root) == ""


def test_lock_release_rejects_release_check_changes_outside_the_bounded_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    make_directory = _fake_make(tmp_path)
    monkeypatch.setenv("PATH", f"{make_directory}:{os.environ['PATH']}")
    monkeypatch.setenv("LOCK_RELEASE_MUTATE", "1")

    with pytest.raises(release_lock.ReleaseLockError, match="unexpected file set: unexpected.txt"):
        release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))


def test_lock_release_does_not_push_when_the_remote_is_not_exactly_one_commit_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release_lock = _release_lock_module()
    root = _source_repository(tmp_path)
    remote = _with_remote(root, tmp_path)
    remote_head = _run(["git", "rev-parse", "HEAD"], root)
    _run(["git", "commit", "--allow-empty", "-qm", "another local commit"], root)
    make_directory = _fake_make(tmp_path)
    monkeypatch.setenv("PATH", f"{make_directory}:{os.environ['PATH']}")

    release_lock.lock_release(root, "0.1.3", date(2026, 8, 27), _fake_uv(tmp_path))

    assert "not pushing origin" in capsys.readouterr().out
    branch = _run(["git", "branch", "--show-current"], root).strip()
    assert (
        _run(["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{branch}"], root)
        == remote_head
    )
