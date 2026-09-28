"""Refresh common trunk-like branches in local Git repositories."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TRUNK_BRANCHES = ("dev", "develop", "development", "main", "master")


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
    return subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, text=True, check=False
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


def _remote_tips(repository: Path, branch: str) -> tuple[_RemoteTip, ...] | str:
    remotes_result = _git(repository, ["remote"])
    if remotes_result.returncode != 0:
        return "unable to inspect remotes"
    tips: list[_RemoteTip] = []
    remotes = sorted(line.strip() for line in remotes_result.stdout.splitlines() if line.strip())
    for remote in remotes:
        exists = _git(repository, ["ls-remote", "--exit-code", remote, f"refs/heads/{branch}"])
        if exists.returncode == 2:
            continue
        if exists.returncode != 0:
            return f"unable to inspect {remote}/{branch}"
        fetched = _git(repository, ["fetch", "--quiet", remote, branch])
        if fetched.returncode != 0:
            return f"unable to fetch {remote}/{branch}"
        tip_result = _git(repository, ["rev-parse", "FETCH_HEAD"])
        if tip_result.returncode != 0:
            return f"unable to inspect fetched {remote}/{branch}"
        tip = tip_result.stdout.strip()
        old_head = _head(repository)
        if old_head is None:
            return "unable to inspect HEAD"
        count_result = _git(repository, ["rev-list", "--count", f"{old_head}..{tip}"])
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


def _inspect(repository: Path, branch: str) -> _PullPlan | str | None:
    old_head = _head(repository)
    if old_head is None:
        return "unable to inspect HEAD"
    tips = _remote_tips(repository, branch)
    if isinstance(tips, str):
        return tips
    selected = _select_tip(repository, tips)
    if isinstance(selected, str):
        return selected
    if selected is None:
        return None
    return _PullPlan(repository, branch, selected, old_head)


def _report_success(plan: _PullPlan, new_head: str) -> str:
    previous = _git(plan.repository, ["rev-parse", "HEAD@{1}"])
    if previous.returncode == 0 and previous.stdout.strip() == plan.old_head:
        change_range = "HEAD@{1}..HEAD"
    else:
        change_range = f"{plan.old_head}..{new_head}"
    return (
        f"{plan.repository}: {plan.tip.remote}/{plan.branch} updated {plan.tip.incoming} commits\n"
        f"  {plan.old_head[:7]} -> {new_head[:7]}\n"
        f"  changes: {change_range}"
    )


def _process(repository: Path, branch: str) -> tuple[str | None, str | None]:
    plan = _inspect(repository, branch)
    if isinstance(plan, str):
        return None, plan
    if plan is None:
        return None, None
    current_head = _head(repository)
    if current_head != plan.old_head:
        return None, "HEAD changed during inspection; refusing to pull"
    pulled = _git(repository, ["pull", plan.tip.remote, plan.branch])
    if pulled.returncode != 0:
        details = pulled.stderr.strip() or pulled.stdout.strip() or "git pull failed"
        return None, details
    new_head = _head(repository)
    if new_head is None:
        return None, "unable to inspect HEAD after pull"
    if new_head == plan.old_head:
        return None, "pull completed without changing HEAD"
    return _report_success(plan, new_head), None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pull-trunk-branches",
        description="Fetch and pull incoming changes for common trunk branches in local clones.",
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

    for repository, branch in selected:
        report, problem = _process(repository, branch)
        if problem is not None:
            print(f"error: {repository}: {problem}", file=sys.stderr)
            diagnostics = True
        elif report is not None:
            print(report)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
