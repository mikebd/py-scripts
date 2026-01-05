import argparse

from util.command import run_command_capture_lines


def sync():
    """
    Synchronize manually installed formulas between hosts.
    """
    parser = argparse.ArgumentParser(description="Synchronize Homebrew formulas.")
    parser.add_argument("remote_host", help="The remote host to compare formulas with.")
    args = parser.parse_args()
    remote_host = args.remote_host

    local_formulas = brew_list_manually_installed_formulas()
    remote_formulas = brew_list_manually_installed_formulas(remote_host)
    local_only_formulas = sorted(list(local_formulas - remote_formulas))
    print(f"Local only formulas:\n{', '.join(local_only_formulas)}")
    remote_only_formulas = sorted(list(remote_formulas - local_formulas))
    print(f"\nRemote only formulas:\n{', '.join(remote_only_formulas)}")


def brew_list_manually_installed_formulas(host: str | None = None) -> set[str]:
    command = ["brew", "list", "--formula", "--installed-on-request"]
    if host:
        command[0] = "/home/linuxbrew/.linuxbrew/bin/" + command[0]
        command = ["ssh", host] + command
    return set(run_command_capture_lines(command))


if __name__ == "__main__":
    sync()
