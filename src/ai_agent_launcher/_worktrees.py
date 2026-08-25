"""Agent-neutral Git worktree creation and strict stacking workflows."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ai_agent_launcher._config import LauncherConfig
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import validate_launcher_creation_inputs
from ai_agent_launcher._lifecycle import LauncherLifecycle
from ai_agent_launcher._models import AgentId, GitMetadataAccess
from ai_agent_launcher._runtime import resolve_worktree


@dataclass(frozen=True)
class CreatedWorktree:
    """The resources created by one completed worktree lifecycle operation."""

    worktree_dir: Path
    branch: str
    launcher: Path


class WorktreeLifecycle:
    """Create Git worktrees and their unpinned generated launchers."""

    def __init__(self, config: LauncherConfig, launchers: LauncherLifecycle) -> None:
        self._config = config
        self._launchers = launchers

    def new(
        self,
        agent_id: AgentId,
        worktree_argument: Path,
        branch: str | None,
        from_ref: str | None,
        launcher_argument: Path | None,
        marker: str,
        preparation_argument: Path | None,
        local_writable_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None,
    ) -> CreatedWorktree:
        """Create one explicit target worktree from a primary-worktree ref."""
        source = resolve_worktree(None)
        primary = self._primary_worktree(source)
        target = self._target_worktree(worktree_argument)
        target_branch = branch or target.name
        self._validate_branch(target_branch)
        start_ref = self._resolve_commit(primary, from_ref or "HEAD")
        launcher = self._launcher_path(agent_id, target.name, launcher_argument)
        preparation = validate_launcher_creation_inputs(
            marker, preparation_argument, local_writable_dirs
        )
        self._preflight(primary, target, target_branch, launcher)
        return self._create(
            primary,
            agent_id,
            target,
            target_branch,
            start_ref,
            launcher,
            marker,
            preparation,
            local_writable_dirs,
            git_metadata_access,
        )

    def stack(
        self,
        agent_id: AgentId,
        suffix: str,
        marker: str,
        preparation_argument: Path | None,
        local_writable_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None,
    ) -> CreatedWorktree:
        """Create strict sibling targets from the current attached worktree HEAD."""
        self._validate_suffix(suffix)
        source = resolve_worktree(None)
        source_branch = self._attached_branch(source)
        target = source.parent / f"{source.name}{suffix}"
        target_branch = f"{source_branch}{suffix}"
        self._validate_branch(target_branch)
        start_ref = self._resolve_commit(source, "HEAD")
        launcher = self._launcher_path(agent_id, target.name, None)
        preparation = validate_launcher_creation_inputs(
            marker, preparation_argument, local_writable_dirs
        )
        self._preflight(source, target, target_branch, launcher)
        return self._create(
            source,
            agent_id,
            target,
            target_branch,
            start_ref,
            launcher,
            marker,
            preparation,
            local_writable_dirs,
            git_metadata_access,
        )

    def _create(
        self,
        source: Path,
        agent_id: AgentId,
        target: Path,
        branch: str,
        start_ref: str,
        launcher: Path,
        marker: str,
        preparation: Path | None,
        local_writable_dirs: tuple[str, ...],
        git_metadata_access: GitMetadataAccess | None,
    ) -> CreatedWorktree:
        created = False
        try:
            self._run_git(
                source,
                "unable to create worktree",
                "worktree",
                "add",
                "-b",
                branch,
                str(target),
                start_ref,
            )
            created = True
            self._launchers.prepare(target, preparation)
            rendered_launcher = self._launchers.create(
                agent_id,
                launcher,
                target,
                marker,
                preparation,
                local_writable_dirs,
                git_metadata_access,
            )
        except BaseException:
            if created:
                self._rollback(source, target, branch)
            raise
        return CreatedWorktree(target, branch, rendered_launcher)

    def _primary_worktree(self, source: Path) -> Path:
        listing = self._run_git(
            source, "unable to list Git worktrees", "worktree", "list", "--porcelain"
        )
        for line in listing.splitlines():
            if line.startswith("worktree "):
                primary = Path(line.removeprefix("worktree "))
                if primary.is_dir():
                    return primary.resolve()
                break
        raise LauncherError("unable to determine primary Git worktree")

    def _target_worktree(self, argument: Path) -> Path:
        candidate = argument.expanduser()
        if candidate.exists() or candidate.is_symlink():
            raise LauncherError(f"worktree path already exists: {candidate}")
        parent = candidate.parent
        if not parent.is_dir():
            raise LauncherError(f"worktree parent is not an existing directory: {parent}")
        return parent.resolve() / candidate.name

    def _launcher_path(
        self,
        agent_id: AgentId,
        worktree_name: str,
        argument: Path | None,
    ) -> Path:
        if argument is not None:
            return argument.expanduser()
        directory = self._config.core.launcher_directory or (Path.home() / ".local" / "bin")
        if directory.exists() and not directory.is_dir():
            raise LauncherError(f"launcher directory is not a directory: {directory}")
        return directory / f"{agent_id}-{worktree_name}"

    def _preflight(self, source: Path, target: Path, branch: str, launcher: Path) -> None:
        if target.exists() or target.is_symlink():
            raise LauncherError(f"worktree path already exists: {target}")
        if launcher.exists() or launcher.is_symlink():
            raise LauncherError(f"launcher path already exists: {launcher}")
        if self._branch_exists(source, branch):
            raise LauncherError(f"target branch already exists: {branch}")

    def _validate_branch(self, branch: str) -> None:
        try:
            result = subprocess.run(
                ["git", "check-ref-format", "--branch", branch],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as error:
            raise LauncherError("git is required to manage worktrees") from error
        if result.returncode != 0:
            raise LauncherError(f"invalid target branch: {branch}")

    def _validate_suffix(self, suffix: str) -> None:
        if not suffix or any(character in suffix for character in ("/", "\\", "\n", "\r")):
            raise LauncherError("suffix must be a non-empty single path-name fragment")

    def _attached_branch(self, source: Path) -> str:
        branch = self._run_git(
            source, "unable to determine source branch", "branch", "--show-current"
        ).strip()
        if not branch:
            raise LauncherError("stack creation requires an attached source branch")
        return branch

    def _resolve_commit(self, source: Path, reference: str) -> str:
        try:
            return self._run_git(
                source,
                f"unable to resolve start ref: {reference}",
                "rev-parse",
                "--verify",
                f"{reference}^{{commit}}",
            ).strip()
        except LauncherError as error:
            raise LauncherError(f"invalid start ref: {reference}") from error

    def _branch_exists(self, source: Path, branch: str) -> bool:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                ],
                check=False,
            )
        except FileNotFoundError as error:
            raise LauncherError("git is required to manage worktrees") from error
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise LauncherError(f"unable to inspect target branch: {branch}")

    def _rollback(self, source: Path, target: Path, branch: str) -> None:
        failures: list[str] = []
        for label, arguments in (
            ("worktree", ("worktree", "remove", "--force", str(target))),
            ("branch", ("branch", "-D", branch)),
        ):
            try:
                self._run_git(source, f"unable to roll back {label}", *arguments)
            except LauncherError as error:
                failures.append(str(error))
        for failure in failures:
            print(f"warning: {failure}", file=sys.stderr)

    def _run_git(self, source: Path, message: str, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(source), *arguments],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as error:
            raise LauncherError("git is required to manage worktrees") from error
        if result.returncode != 0:
            details = result.stderr.strip()
            raise LauncherError(f"{message}: {details}" if details else message)
        return result.stdout
