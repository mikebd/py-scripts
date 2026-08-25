from __future__ import annotations

import argparse
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_agent_launcher._adapters import AgentSessionMetadata
from ai_agent_launcher._config import CoreConfig, LauncherConfig
from ai_agent_launcher._errors import LauncherError
from ai_agent_launcher._launchers import launcher_git_metadata_access, read_launcher
from ai_agent_launcher._lifecycle import LauncherLifecycle
from ai_agent_launcher._models import AgentId, GitMetadataAccess, SessionReference
from ai_agent_launcher._registry import AgentRegistry
from ai_agent_launcher._runtime import RunContext

ObservedLaunch = tuple[RunContext, Mapping[str, object], SessionReference | None, tuple[str, ...]]
ObservedFork = tuple[RunContext, Mapping[str, object], SessionReference, tuple[str, ...]]
ObservedFind = tuple[Mapping[str, object], SessionReference]


@dataclass
class FakeRuntimeAdapter:
    observed: ObservedLaunch | None = None

    @property
    def identifier(self) -> AgentId:
        return AgentId("fake")

    def configure_run_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--fake-option")

    def run(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        arguments: argparse.Namespace,
    ) -> int:
        raise AssertionError("generated launchers must use run_launcher")

    def run_launcher(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        session: SessionReference | None,
        passthrough_args: tuple[str, ...],
    ) -> int:
        self.observed = (context, settings, session, passthrough_args)
        return 17


@dataclass
class FakeSessionLifecycleAdapter(FakeRuntimeAdapter):
    forked_session: SessionReference | None = None
    found_session: AgentSessionMetadata | None = None
    observed_fork: ObservedFork | None = None
    observed_find: ObservedFind | None = None

    def fork_session(
        self,
        context: RunContext,
        settings: Mapping[str, object],
        parent: SessionReference,
        passthrough_args: tuple[str, ...],
    ) -> SessionReference:
        self.observed_fork = (context, settings, parent, passthrough_args)
        if self.forked_session is None:
            raise AssertionError("test must supply a child session")
        return self.forked_session

    def find_session(
        self, settings: Mapping[str, object], session: SessionReference
    ) -> AgentSessionMetadata:
        self.observed_find = (settings, session)
        if self.found_session is None:
            raise AssertionError("test must supply session metadata")
        return self.found_session


def _lifecycle(adapter: FakeRuntimeAdapter) -> tuple[LauncherLifecycle, Mapping[str, object]]:
    identifier = adapter.identifier
    settings: Mapping[str, object] = {"fake_setting": "value"}
    return (
        LauncherLifecycle(
            AgentRegistry((adapter,)),
            LauncherConfig(
                core=CoreConfig(writable_dirs=(), launcher_directory=None),
                agent_settings={identifier: settings},
            ),
        ),
        settings,
    )


def _git_worktree(tmp_path: Path, name: str = "worktree") -> Path:
    worktree = tmp_path / name
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    return worktree


def test_launcher_lifecycle_delegates_generic_metadata_to_runtime_adapter(tmp_path: Path) -> None:
    worktree = _git_worktree(tmp_path)
    launcher = tmp_path / "launcher"
    adapter = FakeRuntimeAdapter()
    identifier = adapter.identifier
    lifecycle, settings = _lifecycle(adapter)

    lifecycle.create(identifier, launcher, worktree, "# generated launcher", None, ())
    lifecycle.pin(launcher, "opaque-session", identifier, replace=False)

    assert lifecycle.run(launcher, ("continue", "--quiet")) == 17
    assert adapter.observed is not None
    context, received_settings, session, passthrough_args = adapter.observed
    assert context.worktree_dir == worktree.resolve()
    assert context.passthrough_args == ("continue", "--quiet")
    assert received_settings == settings
    assert session == SessionReference(identifier, "opaque-session")
    assert passthrough_args == ("continue", "--quiet")


def test_launcher_lifecycle_delegates_fork_to_session_adapter(tmp_path: Path) -> None:
    worktree = _git_worktree(tmp_path)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    inherited = tmp_path / "inherited"
    added = tmp_path / "added"
    inherited.mkdir()
    added.mkdir()
    adapter = FakeSessionLifecycleAdapter(
        forked_session=SessionReference(AgentId("fake"), "child-session")
    )
    lifecycle, settings = _lifecycle(adapter)

    lifecycle.create(
        adapter.identifier,
        source,
        worktree,
        "# generated launcher",
        None,
        (str(inherited),),
        GitMetadataAccess.SHARED,
    )
    lifecycle.pin(source, "parent-session", adapter.identifier, replace=False)

    assert lifecycle.fork(
        source,
        target,
        adapter.identifier,
        (str(added),),
        ("continue", "--quiet"),
    ) == SessionReference(adapter.identifier, "child-session")
    assert adapter.observed_fork is not None
    context, received_settings, parent, passthrough_args = adapter.observed_fork
    assert context.worktree_dir == worktree.resolve()
    assert context.passthrough_args == ("continue", "--quiet")
    assert received_settings == settings
    assert parent == SessionReference(adapter.identifier, "parent-session")
    assert passthrough_args == ("continue", "--quiet")
    target_metadata = read_launcher(target)
    assert target_metadata.session == SessionReference(adapter.identifier, "child-session")
    assert target_metadata.local_writable_dirs == (inherited.resolve(), added.resolve())
    assert launcher_git_metadata_access(target_metadata) is GitMetadataAccess.SHARED

    override_target = tmp_path / "override-target-launcher"
    assert lifecycle.fork(
        source,
        override_target,
        adapter.identifier,
        (),
        (),
        GitMetadataAccess.WORKTREE,
    ) == SessionReference(adapter.identifier, "child-session")
    assert (
        launcher_git_metadata_access(read_launcher(override_target)) is GitMetadataAccess.WORKTREE
    )


def test_launcher_lifecycle_rejects_existing_fork_target_before_preparation_or_fork(
    tmp_path: Path,
) -> None:
    worktree = _git_worktree(tmp_path)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    preparation = tmp_path / "prepare"
    preparation.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    preparation.chmod(0o755)
    target.write_text("existing launcher", encoding="utf-8")
    adapter = FakeSessionLifecycleAdapter(
        forked_session=SessionReference(AgentId("fake"), "child-session")
    )
    lifecycle, _ = _lifecycle(adapter)
    lifecycle.create(
        adapter.identifier,
        source,
        worktree,
        "# generated launcher",
        preparation,
        (),
    )
    lifecycle.pin(source, "parent-session", adapter.identifier, replace=False)

    with pytest.raises(LauncherError, match="launcher path already exists"):
        lifecycle.fork(source, target, adapter.identifier, (), ())

    assert adapter.observed_fork is None


def test_launcher_lifecycle_rejects_dangling_symlink_fork_target_before_fork(
    tmp_path: Path,
) -> None:
    worktree = _git_worktree(tmp_path)
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    target.symlink_to(tmp_path / "missing-launcher")
    adapter = FakeSessionLifecycleAdapter(
        forked_session=SessionReference(AgentId("fake"), "child-session")
    )
    lifecycle, _ = _lifecycle(adapter)
    lifecycle.create(adapter.identifier, source, worktree, "# generated launcher", None, ())
    lifecycle.pin(source, "parent-session", adapter.identifier, replace=False)

    with pytest.raises(LauncherError, match="launcher path already exists"):
        lifecycle.fork(source, target, adapter.identifier, (), ())

    assert target.is_symlink()
    assert adapter.observed_fork is None


def test_launcher_lifecycle_rejects_unusable_fork_target_before_fork(tmp_path: Path) -> None:
    worktree = _git_worktree(tmp_path)
    source = tmp_path / "source-launcher"
    target_parent = tmp_path / "not-a-directory"
    target_parent.write_text("not a directory", encoding="utf-8")
    adapter = FakeSessionLifecycleAdapter(
        forked_session=SessionReference(AgentId("fake"), "child-session")
    )
    lifecycle, _ = _lifecycle(adapter)
    lifecycle.create(adapter.identifier, source, worktree, "# generated launcher", None, ())
    lifecycle.pin(source, "parent-session", adapter.identifier, replace=False)

    with pytest.raises(LauncherError, match="unable to create launcher directory"):
        lifecycle.fork(source, target_parent / "target-launcher", adapter.identifier, (), ())

    assert adapter.observed_fork is None


def test_launcher_lifecycle_delegates_adopt_and_rejects_other_worktrees(tmp_path: Path) -> None:
    worktree = _git_worktree(tmp_path)
    other_worktree = _git_worktree(tmp_path, "other-worktree")
    source = tmp_path / "source-launcher"
    target = tmp_path / "target-launcher"
    adapter = FakeSessionLifecycleAdapter(
        found_session=AgentSessionMetadata(
            SessionReference(AgentId("fake"), "existing-session"),
            worktree.resolve(),
            SessionReference(AgentId("fake"), "parent-session"),
        )
    )
    lifecycle, settings = _lifecycle(adapter)
    lifecycle.create(adapter.identifier, source, worktree, "# generated launcher", None, ())
    lifecycle.pin(source, "parent-session", adapter.identifier, replace=False)

    lifecycle.adopt(source, target, "existing-session", adapter.identifier, ())

    assert adapter.observed_find == (
        settings,
        SessionReference(adapter.identifier, "existing-session"),
    )
    assert read_launcher(target).session == SessionReference(adapter.identifier, "existing-session")
    assert launcher_git_metadata_access(read_launcher(target)) is GitMetadataAccess.WORKTREE

    shared_target = tmp_path / "shared-target-launcher"
    lifecycle.adopt(
        source,
        shared_target,
        "existing-session",
        adapter.identifier,
        (),
        GitMetadataAccess.SHARED,
    )
    assert launcher_git_metadata_access(read_launcher(shared_target)) is GitMetadataAccess.SHARED

    adapter.found_session = AgentSessionMetadata(
        SessionReference(adapter.identifier, "other-session"),
        other_worktree.resolve(),
        None,
    )
    with pytest.raises(LauncherError, match="not launcher worktree"):
        lifecycle.adopt(
            source,
            tmp_path / "rejected-launcher",
            "other-session",
            adapter.identifier,
            (),
        )
