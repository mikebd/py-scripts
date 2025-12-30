import subprocess
from unittest.mock import MagicMock, patch

from util.command import run_command_capture_lines, run_command_capture_text


def test_run_command_capture_text_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="output", stderr="", returncode=0)

        result = run_command_capture_text(["echo", "hello"])

        assert result.stdout == "output"
        mock_run.assert_called_once_with(
            ["echo", "hello"], capture_output=True, text=True, check=True
        )


def test_run_command_capture_lines_success():
    with patch("util.command.run_command_capture_text") as mock_capture:
        mock_capture.return_value = MagicMock(stdout="line1\nline2\n")

        lines = run_command_capture_lines(["ls"])

        assert lines == ["line1", "line2"]


def test_run_command_capture_lines_failure():
    with patch("util.command.run_command_capture_text") as mock_capture:
        mock_capture.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="error")

        lines = run_command_capture_lines(["bad_cmd"])

        assert lines == []
