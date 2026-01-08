from abc import ABC, abstractmethod
from subprocess import CompletedProcess


class Runner(ABC):
    @abstractmethod
    def capture_text(self, command: list[str]) -> CompletedProcess[str]:
        """Runs a shell command and returns the CompletedProcess object."""
        pass

    @abstractmethod
    def capture_lines(self, command: list[str]) -> list[str]:
        """Runs a shell command and returns its output as a list of lines."""
        pass
