import tempfile
from pathlib import Path

from repo.go.validate import is_local_go_repository_root


def test_is_local_go_repository_root_true():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir)
        (path / "go.mod").touch()
        assert is_local_go_repository_root(str(path)) is True


def test_is_local_go_repository_root_false_not_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        assert is_local_go_repository_root(tmp_dir) is False


def test_is_local_go_repository_root_false_subdir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir)
        (path / "go.mod").touch()
        subdir = path / "subdir"
        subdir.mkdir()
        assert is_local_go_repository_root(str(subdir)) is False


def test_is_local_go_repository_root_none():
    result = is_local_go_repository_root(None)
    assert isinstance(result, bool)


def test_is_local_go_repository_root_nonexistent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        nonexistent_path = str(Path(tmp_dir) / "does" / "not" / "exist")
        assert is_local_go_repository_root(nonexistent_path) is False
