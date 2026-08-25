"""Verify that the current source snapshot installs as a Git-tagged uv tool."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import cast


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
