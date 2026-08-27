"""Validate release notes and a Git-tagged distribution installation through uv."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import cast

_RELEASE_HEADING = re.compile(
    r"^## \[v(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)\] - "
    r"(?P<status>Draft|\d{4}-\d{2}-\d{2})$"
)
_CHANGE_CATEGORIES = frozenset({"Added", "Changed", "Deprecated", "Fixed", "Removed", "Security"})


class _ReleaseNote:
    """One parsed release-note heading and its bounded Markdown section."""

    def __init__(
        self,
        version: str,
        status: str,
        start: int,
        end: int,
    ) -> None:
        self.version = version
        self.status = status
        self.start = start
        self.end = end


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", type=Path, required=True)
    return parser.parse_args()


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(name, None)
    return environment


def _run(arguments: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(
        arguments,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=environment,
        text=True,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed: {' '.join(arguments)}\n{details}")
    return result.stdout


def _version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as config_file:
        document = cast(dict[str, object], tomllib.load(config_file))
    project = document.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("pyproject.toml must define project.version")
    version = cast(dict[str, object], project).get("version")
    if not isinstance(version, str):
        raise RuntimeError("pyproject.toml must define project.version")
    return version


def _validate_release_notes(root: Path, version: str) -> None:
    """Require a finalized, complete release-note entry for one distribution version."""
    path = root / "CHANGELOG.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"unable to read release notes: {path}") from error

    entries = _release_note_entries(lines)
    matching = [entry for entry in entries if entry.version == version]
    if not matching:
        raise RuntimeError(f"release notes do not contain v{version}")
    if len(matching) > 1:
        raise RuntimeError(f"release notes contain duplicate v{version} entries")
    entry = matching[0]
    if entry.status == "Draft":
        raise RuntimeError(f"release notes contain a draft for current version: v{version}")
    _validate_release_date(entry)
    _validate_release_entry(lines, entry)


def _release_note_entries(lines: list[str]) -> tuple[_ReleaseNote, ...]:
    headings: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        if not line.startswith("## ["):
            continue
        match = _RELEASE_HEADING.fullmatch(line)
        if match is None:
            raise RuntimeError(f"invalid release-note heading: {line}")
        headings.append((index, match))

    entries: list[_ReleaseNote] = []
    previous_key: tuple[int, int, int] | None = None
    for position, (start, match) in enumerate(headings):
        version_key = (
            int(match["major"]),
            int(match["minor"]),
            int(match["patch"]),
        )
        if previous_key is not None and previous_key <= version_key:
            raise RuntimeError("release notes must be ordered newest to oldest")
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        entries.append(
            _ReleaseNote(
                version=".".join(match[group] for group in ("major", "minor", "patch")),
                status=match["status"],
                start=start,
                end=end,
            )
        )
        previous_key = version_key
    return tuple(entries)


def _validate_release_date(entry: _ReleaseNote) -> None:
    try:
        date.fromisoformat(entry.status)
    except ValueError as error:
        raise RuntimeError(f"release notes have an invalid date for v{entry.version}") from error


def _validate_release_entry(lines: list[str], entry: _ReleaseNote) -> None:
    headings = [
        (index, line.removeprefix("### "))
        for index, line in enumerate(lines[entry.start + 1 : entry.end], start=entry.start + 1)
        if line.startswith("### ")
    ]
    scope_headings = [index for index, heading in headings if heading == "Scope"]
    if len(scope_headings) != 1 or not _section_has_bullet(lines, scope_headings[0], entry.end):
        raise RuntimeError(f"release notes need a non-empty scope for v{entry.version}")
    if not any(
        _section_has_bullet(lines, index, entry.end)
        for index, heading in headings
        if heading in _CHANGE_CATEGORIES
    ):
        raise RuntimeError(f"release notes need a non-empty change category for v{entry.version}")


def _section_has_bullet(lines: list[str], start: int, end: int) -> bool:
    for line in lines[start + 1 : end]:
        if line.startswith("### "):
            return False
        if line.startswith("- ") and line[2:].strip():
            return True
    return False


def _source_paths(root: Path, environment: dict[str, str]) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("unable to list source files for release snapshot")
    paths: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = Path(os.fsdecode(raw_path))
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"invalid source path: {path}")
        paths.append(path)
    return tuple(paths)


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _snapshot_symlink_target(root: Path, destination: Path, source: Path, target: Path) -> str:
    link_target = os.readlink(source)
    if Path(link_target).is_absolute():
        raise RuntimeError(f"release snapshot rejects absolute symlink target: {source}")

    try:
        resolved_source = source.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError(f"release snapshot rejects dangling symlink: {source}") from error
    if not _is_within(resolved_source, root.resolve()):
        raise RuntimeError(f"release snapshot rejects symlink target outside source root: {source}")

    resolved_target = (target.parent / link_target).resolve()
    if not _is_within(resolved_target, destination.resolve()):
        raise RuntimeError(f"release snapshot rejects symlink target outside snapshot: {source}")
    return link_target


def _snapshot(root: Path, destination: Path, environment: dict[str, str], version: str) -> None:
    destination.mkdir()
    symlinks: list[tuple[Path, Path, str]] = []
    for relative_path in _source_paths(root, environment):
        source = root / relative_path
        if not source.exists() and not source.is_symlink():
            continue
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            symlinks.append(
                (source, target, _snapshot_symlink_target(root, destination, source, target))
            )
        else:
            shutil.copy2(source, target)
    for _, target, link_target in symlinks:
        target.symlink_to(link_target)
    for source, target, _ in symlinks:
        try:
            target.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise RuntimeError(f"release snapshot contains dangling symlink: {source}") from error
    _run(["git", "init", "-q"], cwd=destination, environment=environment)
    _run(
        ["git", "config", "user.email", "release-check@example.invalid"],
        cwd=destination,
        environment=environment,
    )
    _run(["git", "config", "user.name", "Release Check"], cwd=destination, environment=environment)
    _run(["git", "add", "--all"], cwd=destination, environment=environment)
    _run(
        ["git", "-c", "commit.gpgSign=false", "commit", "-qm", "release snapshot"],
        cwd=destination,
        environment=environment,
    )
    _run(["git", "tag", f"release-smoke-v{version}"], cwd=destination, environment=environment)


def main() -> int:
    arguments = _parse_args()
    root = Path(__file__).resolve().parents[1]
    version = _version(root)
    _validate_release_notes(root, version)
    environment = _environment()
    with tempfile.TemporaryDirectory(prefix="ai-agent-launcher-release-") as temporary_directory:
        temporary = Path(temporary_directory)
        snapshot = temporary / "snapshot"
        _snapshot(root, snapshot, environment, version)
        tool_directory = temporary / "tools"
        tool_bin_directory = temporary / "bin"
        tool_environment = environment | {
            "UV_CACHE_DIR": str(temporary / "cache"),
            "UV_TOOL_BIN_DIR": str(tool_bin_directory),
            "UV_TOOL_DIR": str(tool_directory),
        }
        source = f"git+{snapshot.as_uri()}@release-smoke-v{version}"
        _run(
            [str(arguments.uv), "tool", "install", "--no-cache", source],
            cwd=temporary,
            environment=tool_environment,
        )
        executable = tool_bin_directory / "ai-agent-launcher"
        installed_version = _run(
            [str(executable), "--version"], cwd=temporary, environment=tool_environment
        ).strip()
        if installed_version != version:
            raise RuntimeError("installed ai-agent-launcher reported an unexpected version")
        _run([str(executable), "--help"], cwd=temporary, environment=tool_environment)
    print(f"release check passed for v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
