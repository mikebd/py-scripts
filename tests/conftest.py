"""Test-wide environment isolation."""

import pytest

_INHERITED_GIT_ENVIRONMENT = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)


@pytest.fixture(autouse=True)
def clear_inherited_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep disposable Git fixtures independent from a caller's repository."""
    for name in _INHERITED_GIT_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
