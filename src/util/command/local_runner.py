import subprocess
from subprocess import CompletedProcess
from typing import override

from util.command.runner import Runner


class LocalRunner(Runner):
    @override
    def capture_text(self, command: list[str]) -> CompletedProcess[str]:
        """Runs a shell command and returns the CompletedProcess object."""
        return subprocess.run(command, capture_output=True, text=True, check=True)

    @override
    def capture_lines(self, command: list[str]) -> list[str]:
        """Runs a shell command and returns its output as a list of lines."""
        result = self.capture_text(command)
        return result.stdout.strip().splitlines()
