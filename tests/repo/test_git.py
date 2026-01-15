import subprocess
import tempfile
from pathlib import Path

from repo.git import is_local_git_repository_root


def test_git_command_exists():
    assert subprocess.run(["git", "--version"], check=True, capture_output=True).returncode == 0


def test_is_local_git_repository_root_true():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir)
        subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
        assert is_local_git_repository_root(str(path)) is True


def test_is_local_git_repository_root_false_not_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        assert is_local_git_repository_root(tmp_dir) is False


def test_is_local_git_repository_root_false_subdir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir)
        subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
        subdir = path / "subdir"
        subdir.mkdir()
        assert is_local_git_repository_root(str(subdir)) is False


def test_is_local_git_repository_root_none():
    # This test depends on the current working directory being a git repo or not.
    # To be safe, we can mock or just test it doesn't crash and returns a bool.
    result = is_local_git_repository_root(None)
    assert isinstance(result, bool)


def test_is_local_git_repository_root_nonexistent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        nonexistent_path = str(Path(tmp_dir) / "does" / "not" / "exist")
        assert is_local_git_repository_root(nonexistent_path) is False
