"""Refresh common trunk-like branches in local Git repositories."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

TRUNK_BRANCHES = ("dev", "develop", "development", "main", "master")

_GIT_CONTEXT_ENVIRONMENT = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)


@dataclass(frozen=True)
class _RemoteTip:
    remote: str
    tip: str
    incoming: int


@dataclass(frozen=True)
class _PullPlan:
    repository: Path
    branch: str
    tip: _RemoteTip
    old_head: str


def _git(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value for name, value in os.environ.items() if name not in _GIT_CONTEXT_ENVIRONMENT
    }
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def discover_repositories(search_roots: tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    """Find validated, resolved local clone/worktree roots beneath search roots."""
    found: set[Path] = set()
    for supplied_root in search_roots:
        root = supplied_root.resolve()
        if not root.is_dir():
            continue
        for current, directories, _ in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            git_marker = current_path / ".git"
            if git_marker.is_dir() or git_marker.is_file():
                candidate = _repository_root(current_path)
                if candidate is not None:
                    found.add(candidate)
                directories[:] = [directory for directory in directories if directory != ".git"]
    return tuple(sorted(found))


def _repository_root(candidate: Path) -> Path | None:
    result = _git(candidate, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    root = Path(result.stdout.strip()).resolve()
    return root if root == candidate.resolve() else None


def _branch(repository: Path) -> str | None:
    result = _git(repository, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else None


def _head(repository: Path) -> str | None:
    result = _git(repository, ["rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else None


def _preflight(repository: Path) -> str | None:
    result = _git(repository, ["status", "--porcelain", "--untracked-files=all"])
    if result.returncode != 0:
        return "unable to inspect worktree status"
    return "worktree has local changes" if result.stdout else None


def _contains(repository: Path, ancestor: str, descendant: str) -> bool | None:
    result = _git(repository, ["merge-base", "--is-ancestor", ancestor, descendant])
    if result.returncode in (0, 1):
        return result.returncode == 0
    return None


def _remote_tips(
    repository: Path,
    branch: str,
    *,
    inspection_repository: Path | None = None,
) -> tuple[_RemoteTip, ...] | str:
    remotes_result = _git(repository, ["remote"])
    if remotes_result.returncode != 0:
        return "unable to inspect remotes"
    tips: list[_RemoteTip] = []
    remotes = sorted(line.strip() for line in remotes_result.stdout.splitlines() if line.strip())
    comparison_repository = inspection_repository or repository
    for index, remote in enumerate(remotes):
        scratch_ref = f"refs/pull-trunk-branches/{index}"
        exists = _git(repository, ["ls-remote", "--exit-code", remote, f"refs/heads/{branch}"])
        if exists.returncode == 2:
            continue
        if exists.returncode != 0:
            return f"unable to inspect {remote}/{branch}"
        if inspection_repository is None:
            fetched = _git(repository, ["fetch", "--quiet", remote, branch])
        else:
            fields = exists.stdout.split()
            if not fields:
                return f"unable to inspect {remote}/{branch}"
            remote_url = _git(repository, ["remote", "get-url", remote])
            if remote_url.returncode != 0:
                return f"unable to inspect {remote}/{branch}"
            tip = fields[0]
            fetched = _git(
                inspection_repository,
                [
                    "fetch",
                    "--quiet",
                    "--no-write-fetch-head",
                    remote_url.stdout.strip(),
                    f"{tip}:{scratch_ref}",
                ],
            )
        if fetched.returncode != 0:
            return f"unable to fetch {remote}/{branch}"
        if inspection_repository is None:
            tip_result = _git(repository, ["rev-parse", "FETCH_HEAD"])
        else:
            tip_result = _git(inspection_repository, ["rev-parse", scratch_ref])
        if tip_result.returncode != 0:
            return f"unable to inspect fetched {remote}/{branch}"
        tip = tip_result.stdout.strip()
        old_head = _head(repository)
        if old_head is None:
            return "unable to inspect HEAD"
        count_result = _git(
            comparison_repository,
            ["rev-list", "--count", f"{old_head}..{tip}"],
        )
        if count_result.returncode != 0:
            return f"unable to count incoming commits from {remote}/{branch}"
        try:
            incoming = int(count_result.stdout.strip())
        except ValueError:
            return f"invalid incoming commit count from {remote}/{branch}"
        if incoming:
            tips.append(_RemoteTip(remote, tip, incoming))
    return tuple(tips)


def _select_tip(repository: Path, tips: tuple[_RemoteTip, ...]) -> _RemoteTip | str | None:
    if not tips:
        return None
    for candidate in sorted(tips, key=lambda tip: tip.remote):
        relations = [_contains(repository, other.tip, candidate.tip) for other in tips]
        if all(relation is True for relation in relations):
            return candidate
        if any(relation is None for relation in relations):
            return "unable to compare incoming remote tips"
    return "incoming remote tips diverge"


def _inspect(
    repository: Path,
    branch: str,
    *,
    inspection_repository: Path | None = None,
) -> _PullPlan | str | None:
    old_head = _head(repository)
    if old_head is None:
        return "unable to inspect HEAD"
    tips = _remote_tips(repository, branch, inspection_repository=inspection_repository)
    if isinstance(tips, str):
        return tips
    selected = _select_tip(inspection_repository or repository, tips)
    if isinstance(selected, str):
        return selected
    if selected is None:
        return None
    return _PullPlan(repository, branch, selected, old_head)


def _report_success(plan: _PullPlan, new_head: str, incoming: int) -> str:
    previous = _git(plan.repository, ["rev-parse", "HEAD@{1}"])
    if previous.returncode == 0 and previous.stdout.strip() == plan.old_head:
        change_range = "HEAD@{1}..HEAD"
    else:
        change_range = f"{plan.old_head}..{new_head}"
    return (
        f"{plan.repository}: {plan.tip.remote}/{plan.branch} updated {incoming} commits\n"
        f"  {plan.old_head[:7]} -> {new_head[:7]}\n"
        f"  changes: {change_range}"
    )


def _report_preview(plan: _PullPlan) -> str:
    return (
        f"{plan.repository}: {plan.tip.remote}/{plan.branch} would update "
        f"{plan.tip.incoming} commits\n"
        f"  {plan.old_head[:7]} -> {plan.tip.tip[:7]}\n"
        f"  changes: {plan.old_head}..{plan.tip.tip}"
    )


def _preview(repository: Path, branch: str) -> tuple[str | None, str | None]:
    try:
        temporary_directory = tempfile.TemporaryDirectory(prefix="pull-trunk-branches-dry-run-")
    except OSError:
        return None, "unable to create isolated inspection repository"
    try:
        with temporary_directory as temporary_path:
            inspection_repository = Path(temporary_path) / "inspection.git"
            cloned = _git(
                Path(temporary_path),
                [
                    "clone",
                    "--bare",
                    "--shared",
                    "--quiet",
                    str(repository),
                    str(inspection_repository),
                ],
            )
            if cloned.returncode != 0:
                return None, "unable to create isolated inspection repository"
            plan = _inspect(
                repository,
                branch,
                inspection_repository=inspection_repository,
            )
            if isinstance(plan, str):
                return None, plan
            if plan is None:
                return None, None
            return _report_preview(plan), None
    except OSError:
        return None, "unable to clean isolated inspection repository"


def _process(repository: Path, branch: str) -> tuple[str | None, str | None]:
    plan = _inspect(repository, branch)
    if isinstance(plan, str):
        return None, plan
    if plan is None:
        return None, None
    current_branch = _branch(repository)
    if current_branch != plan.branch:
        return None, "branch changed during inspection; refusing to pull"
    current_head = _head(repository)
    if current_head != plan.old_head:
        return None, "HEAD changed during inspection; refusing to pull"
    pulled = _git(repository, ["pull", plan.tip.remote, plan.tip.tip])
    if pulled.returncode != 0:
        details = pulled.stderr.strip() or pulled.stdout.strip() or "git pull failed"
        return None, details
    new_head = _head(repository)
    if new_head is None:
        return None, "unable to inspect HEAD after pull"
    if new_head == plan.old_head:
        return None, "pull completed without changing HEAD"
    count_result = _git(repository, ["rev-list", "--count", f"{plan.old_head}..FETCH_HEAD"])
    if count_result.returncode != 0:
        return None, "unable to count incoming commits after pull"
    try:
        incoming = int(count_result.stdout.strip())
    except ValueError:
        return None, "invalid incoming commit count after pull"
    return _report_success(plan, new_head, incoming), None


def _terminate(signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


@contextmanager
def _graceful_termination() -> Generator[None]:
    previous_handlers: dict[int, Callable[[int, FrameType | None], object] | int | None] = {}
    try:
        for termination_signal in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[termination_signal] = signal.signal(termination_signal, _terminate)
        yield
    finally:
        for termination_signal, previous_handler in previous_handlers.items():
            signal.signal(termination_signal, previous_handler)


def _run_selected(
    selected: list[tuple[Path, str]],
    processor: Callable[[Path, str], tuple[str | None, str | None]],
) -> int:
    diagnostics = False
    for repository, branch in selected:
        report, problem = processor(repository, branch)
        if problem is not None:
            print(f"error: {repository}: {problem}", file=sys.stderr)
            diagnostics = True
        elif report is not None:
            print(report)
    return 1 if diagnostics else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pull-trunk-branches",
        description="Fetch and pull incoming changes for common trunk branches in local clones.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect live remote tips without modifying selected repositories",
    )
    parser.add_argument("search_roots", nargs="*", type=Path, metavar="ROOT")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the trunk-branch refresh command."""
    arguments = _build_parser().parse_args(argv)
    roots = tuple(arguments.search_roots) or (Path.cwd(),)
    repositories = discover_repositories(roots)
    selected: list[tuple[Path, str]] = []
    diagnostics = False
    for repository in repositories:
        branch = _branch(repository)
        if branch is not None and branch in TRUNK_BRANCHES:
            selected.append((repository, branch))

    for repository, _ in selected:
        problem = _preflight(repository)
        if problem is not None:
            print(f"error: {repository}: {problem}", file=sys.stderr)
            diagnostics = True
    if diagnostics:
        return 1

    if arguments.dry_run:
        with _graceful_termination():
            return _run_selected(selected, _preview)
    return _run_selected(selected, _process)


if __name__ == "__main__":
    raise SystemExit(main())
