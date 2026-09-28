import signal
import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from repo import pull_trunk_branches as command


def _git(path: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=path, check=True, capture_output=True)


def _git_text(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(path: Path, name: str = "file") -> None:
    (path / name).write_text(name, encoding="utf-8")
    _git(path, "add", name)
    _git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        name,
    )


def _repository_with_incoming_commit(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _commit(repository, "base")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-u", "origin", "main")
    updater = tmp_path / "updater"
    _git(tmp_path, "clone", str(remote), str(updater))
    _commit(updater, "incoming")
    tip = _git_text(updater, "rev-parse", "HEAD")
    _git(updater, "push", "origin", "main")
    return repository, tip


def _git_state(repository: Path) -> tuple[str, str, str, str, bytes | None]:
    fetch_head = Path(_git_text(repository, "rev-parse", "--git-path", "FETCH_HEAD"))
    if not fetch_head.is_absolute():
        fetch_head = repository / fetch_head
    return (
        _git_text(repository, "rev-parse", "HEAD"),
        _git_text(repository, "status", "--porcelain", "--untracked-files=all"),
        _git_text(repository, "for-each-ref", "--format=%(refname) %(objectname)"),
        _git_text(repository, "reflog", "show", "--format=%H"),
        fetch_head.read_bytes() if fetch_head.exists() else None,
    )


def test_git_clears_inherited_git_context(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in command._GIT_CONTEXT_ENVIRONMENT:
        monkeypatch.setenv(name, "inherited")
    monkeypatch.setenv("UNRELATED_VARIABLE", "preserved")
    run = mocker.patch.object(
        command.subprocess,
        "run",
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    )

    command._git(Path("repo"), ["status"])

    environment = run.call_args.kwargs["env"]
    assert "UNRELATED_VARIABLE" in environment
    assert all(name not in environment for name in command._GIT_CONTEXT_ENVIRONMENT)


def test_dry_run_reports_update_without_changing_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository, tip = _repository_with_incoming_commit(tmp_path)
    old_head = _git_text(repository, "rev-parse", "HEAD")
    before = _git_state(repository)
    temporary_root = tmp_path / "temporary"
    temporary_root.mkdir()
    monkeypatch.setattr(command.tempfile, "tempdir", str(temporary_root))

    assert command.main(["--dry-run", str(repository)]) == 0

    assert capsys.readouterr().out == (
        f"{repository}: origin/main would update 1 commits\n"
        f"  {old_head[:7]} -> {tip[:7]}\n"
        f"  changes: {old_head}..{tip}\n"
    )
    assert _git_state(repository) == before
    assert list(temporary_root.iterdir()) == []


def test_dry_run_supports_linked_worktree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository, tip = _repository_with_incoming_commit(tmp_path)
    _git(repository, "checkout", "-b", "side")
    worktree = tmp_path / "linked-worktree"
    _git(repository, "worktree", "add", str(worktree), "main")
    old_head = _git_text(worktree, "rev-parse", "HEAD")
    before = _git_state(worktree)

    assert command.main(["--dry-run", str(worktree)]) == 0

    assert f"  {old_head[:7]} -> {tip[:7]}" in capsys.readouterr().out
    assert _git_state(worktree) == before


def test_discover_repositories_includes_nested_clone_and_worktree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _commit(source)
    nested = tmp_path / "nested"
    nested.mkdir()
    _git(nested, "clone", str(source), str(nested / "clone"))
    worktree = nested / "worktree"
    _git(source, "worktree", "add", str(worktree), "-b", "worktree-branch")

    expected = tuple(sorted((source, nested / "clone", worktree)))
    assert command.discover_repositories([tmp_path]) == expected


def test_select_tip_prefers_containing_tip(mocker: MockerFixture) -> None:
    tips = (
        command._RemoteTip("origin", "ancestor", 1),
        command._RemoteTip("backup", "descendant", 2),
    )

    def contains_side_effect(_repository: Path, ancestor: str, descendant: str) -> bool:
        return (ancestor, descendant) in {
            ("ancestor", "ancestor"),
            ("ancestor", "descendant"),
            ("descendant", "descendant"),
        }

    contains = mocker.patch.object(
        command,
        "_contains",
        side_effect=contains_side_effect,
    )

    assert command._select_tip(Path("repo"), tips) == tips[1]
    contains.assert_any_call(Path("repo"), "ancestor", "descendant")


def test_select_tip_prefers_lexical_remote_for_equal_tips(mocker: MockerFixture) -> None:
    tips = (
        command._RemoteTip("zulu", "tip", 2),
        command._RemoteTip("alpha", "tip", 2),
    )

    mocker.patch.object(command, "_contains", return_value=True)

    assert command._select_tip(Path("repo"), tips) == tips[1]


def test_select_tip_rejects_divergence(mocker: MockerFixture) -> None:
    tips = (
        command._RemoteTip("origin", "left", 1),
        command._RemoteTip("backup", "right", 1),
    )
    mocker.patch.object(command, "_contains", return_value=False)
    assert command._select_tip(Path("repo"), tips) == "incoming remote tips diverge"


def test_remote_tips_silently_skips_missing_branch(mocker: MockerFixture) -> None:
    def fake_git(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if arguments == ["remote"]:
            return subprocess.CompletedProcess([], 0, "origin\nbackup\n", "")
        if arguments[:2] == ["ls-remote", "--exit-code"] and arguments[2] == "backup":
            return subprocess.CompletedProcess([], 2, "", "")
        if arguments[:2] == ["ls-remote", "--exit-code"]:
            return subprocess.CompletedProcess([], 0, "tip refs/heads/main\n", "")
        if arguments[:2] == ["fetch", "--quiet"]:
            return subprocess.CompletedProcess([], 0, "", "")
        if arguments == ["rev-parse", "FETCH_HEAD"]:
            return subprocess.CompletedProcess([], 0, "tip\n", "")
        if arguments == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess([], 0, "old\n", "")
        return subprocess.CompletedProcess([], 0, "1\n", "")

    mocker.patch.object(command, "_git", side_effect=fake_git)

    result = command._remote_tips(Path("repo"), "main")

    assert result == (command._RemoteTip("origin", "tip", 1),)


def test_remote_tips_rejects_fetch_failure(mocker: MockerFixture) -> None:
    def fake_git(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if arguments == ["remote"]:
            return subprocess.CompletedProcess([], 0, "origin\n", "")
        if arguments[:2] == ["ls-remote", "--exit-code"]:
            return subprocess.CompletedProcess([], 0, "tip refs/heads/main\n", "")
        return subprocess.CompletedProcess([], 1, "", "network failure")

    mocker.patch.object(command, "_git", side_effect=fake_git)

    assert command._remote_tips(Path("repo"), "main") == "unable to fetch origin/main"


def test_remote_tips_fetches_live_branch_into_scratch(mocker: MockerFixture) -> None:
    repository = Path("repo")
    scratch = Path("scratch")

    def fake_git(path: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if path == repository and arguments == ["remote"]:
            return subprocess.CompletedProcess([], 0, "origin\n", "")
        if path == repository and arguments[:2] == ["ls-remote", "--exit-code"]:
            return subprocess.CompletedProcess([], 0, "inspected refs/heads/main\n", "")
        if path == repository and arguments == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess([], 0, "remote-url\n", "")
        if path == scratch and arguments == [
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            "remote-url",
            "refs/heads/main:refs/pull-trunk-branches/0",
        ]:
            return subprocess.CompletedProcess([], 0, "", "")
        if path == scratch and arguments == ["rev-parse", "refs/pull-trunk-branches/0"]:
            return subprocess.CompletedProcess([], 0, "inspected\n", "")
        if path == repository and arguments == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess([], 0, "old\n", "")
        if path == scratch and arguments == ["rev-list", "--count", "old..inspected"]:
            return subprocess.CompletedProcess([], 0, "1\n", "")
        raise AssertionError((path, arguments))

    mocker.patch.object(command, "_git", side_effect=fake_git)

    assert command._remote_tips(repository, "main", inspection_repository=scratch) == (
        command._RemoteTip("origin", "inspected", 1),
    )


def test_preview_reports_scratch_clone_failure(mocker: MockerFixture) -> None:
    mocker.patch.object(
        command,
        "_git",
        return_value=subprocess.CompletedProcess([], 1, "", "clone failed"),
    )

    report, problem = command._preview(Path("repo"), "main")

    assert report is None
    assert problem == "unable to create isolated inspection repository"


def test_process_pulls_inspected_tip_and_reports_reflog_range(mocker: MockerFixture) -> None:
    repository = Path("repo")
    old = "1234567890abcdef"
    new = "fedcba0987654321"
    plan = command._PullPlan(repository, "main", command._RemoteTip("origin", "tip", 3), old)
    mocker.patch.object(command, "_inspect", return_value=plan)
    mocker.patch.object(command, "_branch", return_value="main")
    heads = iter((old, new))
    mocker.patch.object(command, "_head", side_effect=heads)
    fake_git = mocker.patch.object(command, "_git")
    fake_git.side_effect = [
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, "4\n", ""),
        subprocess.CompletedProcess([], 0, old, ""),
    ]

    report, problem = command._process(repository, "main")

    assert problem is None
    assert report is not None
    assert "origin/main updated 4 commits" in report
    assert "changes: HEAD@{1}..HEAD" in report
    assert fake_git.call_args_list[0].args == (repository, ["pull", ".", "tip"])
    assert fake_git.call_args_list[1].args == (
        repository,
        ["rev-list", "--count", f"{old}..FETCH_HEAD"],
    )


def test_process_reports_full_sha_range_when_reflog_does_not_match(mocker: MockerFixture) -> None:
    repository = Path("repo")
    old = "1234567890abcdef"
    new = "fedcba0987654321"
    plan = command._PullPlan(repository, "main", command._RemoteTip("origin", "tip", 1), old)
    mocker.patch.object(command, "_inspect", return_value=plan)
    mocker.patch.object(command, "_branch", return_value="main")
    mocker.patch.object(command, "_head", side_effect=(old, new))
    mocker.patch.object(
        command,
        "_git",
        side_effect=(
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "1\n", ""),
            subprocess.CompletedProcess([], 0, "different", ""),
        ),
    )

    report, problem = command._process(repository, "main")

    assert problem is None
    assert report is not None
    assert f"changes: {old}..{new}" in report


def test_process_rejects_branch_change_before_pull(mocker: MockerFixture) -> None:
    repository = Path("repo")
    plan = command._PullPlan(
        repository,
        "main",
        command._RemoteTip("origin", "tip", 1),
        "1234567890abcdef",
    )
    mocker.patch.object(command, "_inspect", return_value=plan)
    mocker.patch.object(command, "_branch", return_value="develop")
    head = mocker.patch.object(command, "_head")
    git = mocker.patch.object(command, "_git")

    report, problem = command._process(repository, "main")

    assert report is None
    assert problem == "branch changed during inspection; refusing to pull"
    head.assert_not_called()
    git.assert_not_called()


def test_process_reports_count_failure_after_pull(mocker: MockerFixture) -> None:
    repository = Path("repo")
    old = "1234567890abcdef"
    new = "fedcba0987654321"
    plan = command._PullPlan(repository, "main", command._RemoteTip("origin", "tip", 1), old)
    mocker.patch.object(command, "_inspect", return_value=plan)
    mocker.patch.object(command, "_branch", return_value="main")
    mocker.patch.object(command, "_head", side_effect=(old, new))
    mocker.patch.object(
        command,
        "_git",
        side_effect=(
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 1, "", "count failed"),
        ),
    )

    report, problem = command._process(repository, "main")

    assert report is None
    assert problem == "unable to count incoming commits after pull"


def test_graceful_termination_restores_handlers(mocker: MockerFixture) -> None:
    original_handlers = {
        signal.SIGTERM: signal.SIG_DFL,
        signal.SIGHUP: signal.SIG_IGN,
    }
    calls: list[tuple[signal.Signals, Any]] = []

    def replace_handler(signum: signal.Signals, handler: Any) -> Any:
        calls.append((signum, handler))
        return original_handlers[signum]

    mocker.patch.object(command.signal, "signal", side_effect=replace_handler)

    with command._graceful_termination():
        installed = dict(calls)
        for termination_signal in original_handlers:
            with pytest.raises(SystemExit) as error:
                installed[termination_signal](termination_signal, None)
            assert error.value.code == 128 + termination_signal

    assert calls[2:] == list(original_handlers.items())


def test_main_dry_run_uses_preview(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path("repository")
    mocker.patch.object(command, "discover_repositories", return_value=(repository,))
    mocker.patch.object(command, "_branch", return_value="main")
    mocker.patch.object(command, "_preflight", return_value=None)
    preview = mocker.patch.object(command, "_preview", return_value=("would update", None))
    process = mocker.patch.object(command, "_process")
    mocker.patch.object(command, "_graceful_termination", return_value=nullcontext())

    assert command.main(["--dry-run", "root"]) == 0

    assert capsys.readouterr().out == "would update\n"
    preview.assert_called_once_with(repository, "main")
    process.assert_not_called()


def test_main_dirty_repository_gates_all_processing(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    first = Path("first")
    second = Path("second")
    mocker.patch.object(command, "discover_repositories", return_value=(first, second))
    mocker.patch.object(command, "_branch", side_effect=("main", "develop"))
    preflight = mocker.patch.object(command, "_preflight", side_effect=("dirty", None))
    process = mocker.patch.object(command, "_process")

    assert command.main(["root"]) == 1
    assert "first: dirty" in capsys.readouterr().err
    assert preflight.call_args_list[0].args == (first,)
    assert preflight.call_args_list[1].args == (second,)
    process.assert_not_called()


def test_main_continues_after_repository_pull_failure(
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = Path("first")
    second = Path("second")
    mocker.patch.object(command, "discover_repositories", return_value=(first, second))
    mocker.patch.object(command, "_branch", side_effect=("main", "main"))
    mocker.patch.object(command, "_preflight", return_value=None)
    process = mocker.patch.object(
        command,
        "_process",
        side_effect=((None, "pull failed"), ("second updated", None)),
    )

    assert command.main(["root"]) == 1
    captured = capsys.readouterr()
    assert "first: pull failed" in captured.err
    assert "second updated" in captured.out
    assert process.call_count == 2
