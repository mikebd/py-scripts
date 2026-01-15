from pathlib import Path


def path_or_cwd(path: str | None = None) -> tuple[Path, bool]:
    """Returns a Path object and validation status.

    Args:
        path: Optional path string to validate. If None, uses the current working directory.

    Returns:
        A tuple containing the Path object and a boolean indicating whether the path
        exists and is a directory. If the path is valid, returns (path, True). Otherwise,
        returns (path, False).
    """
    check_path = Path(path) if path is not None else Path.cwd()

    if check_path.exists() and check_path.is_dir():
        return check_path, True

    return check_path, False
