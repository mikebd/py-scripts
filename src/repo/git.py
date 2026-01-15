import subprocess
from pathlib import Path

from util.dir import path_or_cwd


def is_local_git_repository_root(path: str | None = None) -> bool:
    """
    Checks if the given path is a local git repository root.
    If the path is None, use the current working directory.
    """
    check_path, ok = path_or_cwd(path)
    if not ok:
        return False

    try:
        # We use git rev-parse --show-toplevel to check if we are at the root of a git repo.
        # We set cwd to the path we want to check.
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=check_path,
            capture_output=True,
            text=True,
            check=True,
        )
        # If the path is the root, rev-parse --show-toplevel will return the absolute path.
        # We compare it with the absolute path of check_path.
        return Path(result.stdout.strip()).resolve() == check_path.resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
