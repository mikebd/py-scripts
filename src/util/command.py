import subprocess
import sys
from subprocess import CompletedProcess


def run_command_capture_text(command: list[str]) -> CompletedProcess[str]:
    """Runs a shell command and returns the CompletedProcess object."""
    return subprocess.run(command, capture_output=True, text=True, check=True)


def run_command_capture_lines(command: list[str]) -> list[str]:
    """Runs a shell command and returns its output as a list of lines."""
    try:
        result = run_command_capture_text(command)
        return result.stdout.strip().splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(command)}: {e.stderr}", file=sys.stderr)
        return []
