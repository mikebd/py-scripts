from util.dir import path_or_cwd


def is_local_go_repository_root(path: str | None = None) -> bool:
    """
    Checks if the given path is a local Go repository root.
    A Go repository root is identified by the presence of a 'go.mod' file.
    If the path is None, use the current working directory.

    Assumes go >= 1.16 (module mode always enabled).
    """
    check_path, ok = path_or_cwd(path)
    if not ok:
        return False

    # A Go repository root must have a go.mod file.
    go_mod_file = check_path / "go.mod"
    return go_mod_file.exists() and go_mod_file.is_file()
