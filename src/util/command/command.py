from subprocess import CompletedProcess

from util.command.local_runner import LocalRunner
from util.command.runner import Runner

_default_runner = LocalRunner()


def capture_text(command: list[str], runner: Runner = _default_runner) -> CompletedProcess[str]:
    return runner.capture_text(command)


def capture_lines(command: list[str], runner: Runner = _default_runner) -> list[str]:
    return runner.capture_lines(command)
