import argparse

from util.command.command import capture_lines
from util.command.runner import Runner
from util.command.ssh_runner import SshRunner


def diff():
    """
    Compare manually installed formulas between hosts.
    """
    parser = argparse.ArgumentParser(description="Compare Homebrew formulas.")
    parser.add_argument("remote_host", help="The remote host to compare formulas with.")
    args = parser.parse_args()
    remote_host = args.remote_host
    ssh_runner = SshRunner(host=remote_host)

    local_formulas = brew_list_manually_installed_formulas()
    remote_formulas = brew_list_manually_installed_formulas(ssh_runner)
    local_only_formulas = sorted(list(local_formulas - remote_formulas))
    print(f"Local only formulas:\n{', '.join(local_only_formulas)}")
    remote_only_formulas = sorted(list(remote_formulas - local_formulas))
    print(f"\nRemote only formulas:\n{', '.join(remote_only_formulas)}")


def brew_list_manually_installed_formulas(runner: Runner | None = None) -> set[str]:
    command = ["brew", "list", "--formula", "--installed-on-request"]
    _brew_ssh_path(command, runner)
    kwargs = {"runner": runner} if runner else {}
    return set(capture_lines(command, **kwargs))


def _brew_ssh_path(command: list[str], runner: Runner | None = None):
    if runner and isinstance(runner, SshRunner):
        command[0] = "/home/linuxbrew/.linuxbrew/bin/" + command[0]


if __name__ == "__main__":
    diff()
