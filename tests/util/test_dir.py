import os
import tempfile
from pathlib import Path

from util.dir import path_or_cwd


def test_path_or_cwd_none():
    path, ok = path_or_cwd(None)
    assert path == Path.cwd()
    assert ok is True


def test_path_or_cwd_valid_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path, ok = path_or_cwd(tmp_dir)
        # TemporaryDirectory might return a path that needs resolving depending on OS
        assert path.resolve() == Path(tmp_dir).resolve()
        assert ok is True


def test_path_or_cwd_invalid_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        invalid_path = os.path.join(tmp_dir, "nonexistent")
        path, ok = path_or_cwd(invalid_path)
        assert path == Path(invalid_path)
        assert ok is False


def test_path_or_cwd_is_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "test_file.txt")
        with open(file_path, "w") as f:
            f.write("hello")

        path, ok = path_or_cwd(file_path)
        assert path == Path(file_path)
        assert ok is False
