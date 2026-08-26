from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _release_check_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "check_release.py"
    specification = importlib.util.spec_from_file_location("check_release", script)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _source_repository(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def _add(path: Path, *relative_paths: str) -> None:
    subprocess.run(["git", "add", "--", *relative_paths], cwd=path, check=True)


def _write_changelog(path: Path, contents: str) -> None:
    (path / "CHANGELOG.md").write_text(contents, encoding="utf-8")


def test_release_notes_accept_current_finalized_entry_with_future_draft(tmp_path: Path) -> None:
    release_check = _release_check_module()
    _write_changelog(
        tmp_path,
        """# Changelog

## [v0.1.2] - Draft

### Scope

- `example`

### Added

- Draft change.

## [v0.1.1] - 2026-08-26

### Scope

- `example`

### Fixed

- Released change.
""",
    )

    release_check._validate_release_notes(tmp_path, "0.1.1")


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("# Changelog\n", "do not contain v0.1.1"),
        (
            """# Changelog

## [v0.1.1] - Draft

### Scope

- `example`

### Added

- Draft change.
""",
            "draft for current version",
        ),
        (
            """# Changelog

## [v0.1.1] - 2026-02-30

### Scope

- `example`

### Added

- Invalid calendar date.
""",
            "invalid date",
        ),
        (
            """# Changelog

## [v0.1.1] - 2026-08-26

### Added

- Missing scope.
""",
            "non-empty scope",
        ),
        (
            """# Changelog

## [v0.1.1] - 2026-08-26

### Scope

- `example`
""",
            "non-empty change category",
        ),
        (
            """# Changelog

## [v0.1.0] - 2026-08-25

### Scope

- `example`

### Added

- Older entry appears first.

## [v0.1.1] - 2026-08-26

### Scope

- `example`

### Added

- Newer entry appears second.
""",
            "newest to oldest",
        ),
    ],
)
def test_release_notes_reject_invalid_current_entry(
    tmp_path: Path, contents: str, message: str
) -> None:
    release_check = _release_check_module()
    _write_changelog(tmp_path, contents)

    with pytest.raises(RuntimeError, match=message):
        release_check._validate_release_notes(tmp_path, "0.1.1")


def test_snapshot_preserves_valid_relative_in_repository_symlink(tmp_path: Path) -> None:
    release_check = _release_check_module()
    source = _source_repository(tmp_path)
    destination = tmp_path / "snapshot"
    target = source / "target.txt"
    target.write_text("target\n", encoding="utf-8")
    link = source / "links" / "target.txt"
    link.parent.mkdir()
    link.symlink_to("../target.txt")
    _add(source, "target.txt", "links/target.txt")

    release_check._snapshot(source, destination, os.environ.copy(), "0.0.0")

    copied_link = destination / "links" / "target.txt"
    assert copied_link.is_symlink()
    assert os.readlink(copied_link) == "../target.txt"
    assert copied_link.read_text(encoding="utf-8") == "target\n"


@pytest.mark.parametrize(
    ("link_target", "message"),
    [
        ("missing.txt", "dangling symlink"),
        ("/tmp/outside.txt", "absolute symlink"),
        ("../outside.txt", "outside source root"),
    ],
)
def test_snapshot_rejects_unsafe_symlink_targets(
    tmp_path: Path, link_target: str, message: str
) -> None:
    release_check = _release_check_module()
    source = _source_repository(tmp_path)
    destination = tmp_path / "snapshot"
    if link_target == "../outside.txt":
        (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    link = source / "link.txt"
    link.symlink_to(link_target)
    _add(source, "link.txt")

    with pytest.raises(RuntimeError, match=message):
        release_check._snapshot(source, destination, os.environ.copy(), "0.0.0")


def test_snapshot_rejects_relative_target_that_escapes_destination(tmp_path: Path) -> None:
    release_check = _release_check_module()
    source = _source_repository(tmp_path)
    destination = tmp_path / "snapshot"
    target = source / "target.txt"
    target.write_text("target\n", encoding="utf-8")
    link = source / "link.txt"
    link.symlink_to(f"../{source.name}/target.txt")
    _add(source, "target.txt", "link.txt")

    with pytest.raises(RuntimeError, match="outside snapshot"):
        release_check._snapshot(source, destination, os.environ.copy(), "0.0.0")
