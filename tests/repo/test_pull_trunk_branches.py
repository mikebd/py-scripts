import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repo import pull_trunk_branches as command


def _git(path: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=path, check=True, capture_output=True)


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


def test_select_tip_prefers_containing_tip_and_lexical_equal_tie(
    mocker: MockerFixture,
) -> None:
    tips = (
        command._RemoteTip("zulu", "tip", 2),
        command._RemoteTip("alpha", "tip", 2),
        command._RemoteTip("middle", "descendant", 1),
    )
    contains = mocker.patch.object(command, "_contains", return_value=True)
    assert command._select_tip(Path("repo"), tips) == tips[1]
    contains.assert_called()


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


def test_process_uses_exact_pull_and_reports_reflog_range(mocker: MockerFixture) -> None:
    repository = Path("repo")
    old = "1234567890abcdef"
    new = "fedcba0987654321"
    plan = command._PullPlan(repository, "main", command._RemoteTip("origin", "tip", 3), old)
    mocker.patch.object(command, "_inspect", return_value=plan)
    heads = iter((old, new))
    mocker.patch.object(command, "_head", side_effect=heads)
    fake_git = mocker.patch.object(command, "_git")
    fake_git.side_effect = [
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, old, ""),
    ]

    report, problem = command._process(repository, "main")

    assert problem is None
    assert report is not None
    assert "origin/main updated 3 commits" in report
    assert "changes: HEAD@{1}..HEAD" in report
    assert fake_git.call_args_list[0].args == (repository, ["pull", "origin", "main"])


def test_process_reports_full_sha_range_when_reflog_does_not_match(mocker: MockerFixture) -> None:
    repository = Path("repo")
    old = "1234567890abcdef"
    new = "fedcba0987654321"
    plan = command._PullPlan(repository, "main", command._RemoteTip("origin", "tip", 1), old)
    mocker.patch.object(command, "_inspect", return_value=plan)
    mocker.patch.object(command, "_head", side_effect=(old, new))
    mocker.patch.object(
        command,
        "_git",
        side_effect=(
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "different", ""),
        ),
    )

    report, problem = command._process(repository, "main")

    assert problem is None
    assert report is not None
    assert f"changes: {old}..{new}" in report


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
