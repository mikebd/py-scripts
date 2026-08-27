#!/usr/bin/env python3
"""Finalize, validate, commit, and conditionally push one repository release."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tomllib
from datetime import date
from pathlib import Path
from typing import cast

_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MARKER_START = "<!-- release-lock: current-version-examples:start -->"
_MARKER_END = "<!-- release-lock: current-version-examples:end -->"
_MARKED_VERSION_PATTERN = re.compile(r"\bv(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\b")


class ReleaseLockError(RuntimeError):
    """The repository cannot safely complete a release-lock operation."""


def _parse_version(value: str) -> str:
    if _VERSION_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("version must use MAJOR.MINOR.PATCH without a prerelease")
    return value


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", type=_parse_version)
    parser.add_argument("--date", type=_parse_date, default=date.today())
    parser.add_argument("--uv", type=Path)
    return parser.parse_args()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(arguments: list[str], *, cwd: Path) -> str:
    result = subprocess.run(arguments, capture_output=True, check=False, cwd=cwd, text=True)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise ReleaseLockError(f"command failed: {' '.join(arguments)}\n{details}")
    return result.stdout


def _version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ReleaseLockError(f"invalid project version: {value}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _require_clean_attached_worktree(root: Path) -> str:
    top_level = Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=root).strip()).resolve()
    if top_level != root.resolve():
        raise ReleaseLockError(f"release lock must run from its repository root: {root}")
    branch = _run(["git", "branch", "--show-current"], cwd=root).strip()
    if not branch:
        raise ReleaseLockError("release lock requires an attached Git branch")
    status = _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root)
    if status:
        raise ReleaseLockError("release lock requires a clean Git worktree")
    return branch


def _project_metadata(root: Path) -> tuple[str, str]:
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as configuration:
            document = cast(dict[str, object], tomllib.load(configuration))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReleaseLockError(f"unable to read {path}") from error
    project = document.get("project")
    if not isinstance(project, dict):
        raise ReleaseLockError("pyproject.toml must define [project]")
    values = cast(dict[str, object], project)
    name = values.get("name")
    version = values.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ReleaseLockError("pyproject.toml must define project.name and project.version")
    _version_key(version)
    return name, version


def _replace_project_version(contents: str, current: str, target: str) -> str:
    source = f'version = "{current}"'
    if contents.count(source) != 1:
        raise ReleaseLockError("pyproject.toml must contain exactly one current project version")
    return contents.replace(source, f'version = "{target}"')


def _finalize_changelog(contents: str, target: str, release_date: date) -> str:
    source = f"## [v{target}] - Draft"
    if contents.count(source) != 1:
        raise ReleaseLockError(f"CHANGELOG.md must contain exactly one Draft entry for v{target}")
    return contents.replace(source, f"## [v{target}] - {release_date.isoformat()}")


def _replace_marked_documentation_version(contents: str, current: str, target: str) -> str:
    start = contents.find(_MARKER_START)
    end = contents.find(_MARKER_END)
    if start == -1 or end == -1 or end <= start or contents.count(_MARKER_START) != 1:
        raise ReleaseLockError(
            "documentation needs one ordered current-version example marker block"
        )
    if contents.count(_MARKER_END) != 1:
        raise ReleaseLockError(
            "documentation needs one ordered current-version example marker block"
        )
    marked = contents[start : end + len(_MARKER_END)]
    versions = {
        match.group(0).removeprefix("v") for match in _MARKED_VERSION_PATTERN.finditer(marked)
    }
    if not versions:
        raise ReleaseLockError("documentation current-version example marker block has no versions")
    if versions != {current}:
        raise ReleaseLockError("documentation current-version examples must match project.version")
    return (
        contents[:start]
        + marked.replace(f"v{current}", f"v{target}")
        + contents[end + len(_MARKER_END) :]
    )


def _write(path: Path, contents: str) -> None:
    try:
        path.write_text(contents, encoding="utf-8")
    except OSError as error:
        raise ReleaseLockError(f"unable to write {path}") from error


def _verify_locked_version(root: Path, name: str, target: str) -> None:
    path = root / "uv.lock"
    try:
        with path.open("rb") as lock_file:
            document = cast(dict[str, object], tomllib.load(lock_file))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReleaseLockError(f"unable to read {path}") from error
    packages = document.get("package")
    if not isinstance(packages, list):
        raise ReleaseLockError("uv.lock must contain package entries")
    matches = 0
    for package in cast(list[object], packages):
        if not isinstance(package, dict):
            continue
        values = cast(dict[str, object], package)
        if values.get("name") == name and values.get("version") == target:
            matches += 1
    if matches != 1:
        raise ReleaseLockError(f"uv.lock must contain {name} at version {target}")


def _release_files(root: Path) -> tuple[Path, ...]:
    return (
        root / "CHANGELOG.md",
        root / "docs" / "ai-agent-launcher" / "README.md",
        root / "pyproject.toml",
        root / "uv.lock",
    )


def _verify_controlled_changes(root: Path) -> tuple[Path, ...]:
    _run(["git", "diff", "--check"], cwd=root)
    changed: set[Path] = set()
    for arguments in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        changed.update(
            root / relative_path for relative_path in _run(arguments, cwd=root).splitlines()
        )
    expected = set(_release_files(root))
    if changed != expected:
        unexpected = ", ".join(str(path.relative_to(root)) for path in sorted(changed ^ expected))
        raise ReleaseLockError(f"release lock changed an unexpected file set: {unexpected}")
    return tuple(sorted(expected))


def _push_one_commit_ahead(root: Path, branch: str) -> None:
    reference = f"refs/heads/{branch}"
    for remote in _run(["git", "remote"], cwd=root).splitlines():
        remote_heads = _run(["git", "ls-remote", "--heads", remote, reference], cwd=root)
        if not remote_heads.strip():
            print(f"not pushing {remote}: it does not already have {branch}")
            continue
        _run(["git", "fetch", "--quiet", remote, reference], cwd=root)
        counts = _run(["git", "rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD"], cwd=root)
        if counts.split() != ["1", "0"]:
            print(f"not pushing {remote}: {branch} is not exactly one commit behind HEAD")
            continue
        _run(["git", "push", remote, f"HEAD:{reference}"], cwd=root)
        print(f"pushed release-lock commit to {remote}/{branch}")


def lock_release(root: Path, target: str, release_date: date, uv: Path) -> None:
    """Lock one Draft release, then commit and safely publish the bounded changes."""
    branch = _require_clean_attached_worktree(root)
    name, current = _project_metadata(root)
    if _version_key(target) <= _version_key(current):
        raise ReleaseLockError(
            f"target version {target} must be newer than current version {current}"
        )

    pyproject = root / "pyproject.toml"
    changelog = root / "CHANGELOG.md"
    documentation = root / "docs" / "ai-agent-launcher" / "README.md"
    try:
        project_contents = pyproject.read_text(encoding="utf-8")
        changelog_contents = changelog.read_text(encoding="utf-8")
        documentation_contents = documentation.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseLockError("unable to read release-lock source files") from error

    updated_project = _replace_project_version(project_contents, current, target)
    updated_changelog = _finalize_changelog(changelog_contents, target, release_date)
    updated_documentation = _replace_marked_documentation_version(
        documentation_contents, current, target
    )
    _write(pyproject, updated_project)
    _write(changelog, updated_changelog)
    _write(documentation, updated_documentation)
    _run([str(uv), "lock", "--offline"], cwd=root)
    _verify_locked_version(root, name, target)
    _run(["make", "release-check"], cwd=root)
    release_files = _verify_controlled_changes(root)
    _run(["git", "add", "--", *(str(path.relative_to(root)) for path in release_files)], cwd=root)
    _run(["git", "commit", "-m", f"chore(release): lock v{target}"], cwd=root)
    _push_one_commit_ahead(root, branch)


def main() -> int:
    arguments = _parse_args()
    uv = arguments.uv or shutil.which("uv")
    if uv is None:
        raise SystemExit("error: uv is required; pass --uv or add uv to PATH")
    try:
        lock_release(_repository_root(), arguments.version, arguments.date, Path(uv))
    except ReleaseLockError as error:
        print(f"error: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
