import subprocess
import sys
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import override

from util.command.runner import Runner


@dataclass(frozen=True)
class SshRunner(Runner):
    host: str
    user: str | None = None
    port: int = 22
    connect_timeout_seconds: int = 2

    @property
    def _connection_string(self) -> str:
        user = f"{self.user}@" if self.user else ""
        port = f":{self.port}" if self.port != 22 else ""
        return f"ssh://{user}{self.host}{port}"

    def __post_init__(self):
        if not self.host:
            raise ValueError("Host cannot be empty")
        if self.port <= 0:
            raise ValueError("Port must be positive")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("Connect timeout must be positive")

    def __str__(self) -> str:
        return (
            f"SSH to {self._connection_string} (connect timeout: {self.connect_timeout_seconds}s)"
        )

    def _ssh_command(self, command: list[str]) -> list[str]:
        """Returns the SSH command to run the given command over SSH."""
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout_seconds}",
            self._connection_string,
        ] + command

    @override
    def capture_text(self, command: list[str]) -> CompletedProcess[str]:
        """Runs a shell command over SSH and returns the CompletedProcess object."""
        command = self._ssh_command(command)
        return subprocess.run(command, capture_output=True, text=True, check=True)

    @override
    def capture_lines(self, command: list[str]) -> list[str]:
        """Runs a shell command over SSH and returns its output as a list of lines."""
        try:
            result = self.capture_text(command)
            return result.stdout.strip().splitlines()
        except subprocess.CalledProcessError as e:
            print(f"Error running command {' '.join(command)}: {e.stderr}", file=sys.stderr)
            return []
