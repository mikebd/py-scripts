"""Test-wide environment isolation."""

import pytest

_INHERITED_GIT_ENVIRONMENT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


@pytest.fixture(autouse=True)
def clear_inherited_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep disposable Git fixtures independent from a caller's repository."""
    for name in _INHERITED_GIT_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
