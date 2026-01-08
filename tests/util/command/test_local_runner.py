import subprocess

from pytest_mock import MockerFixture

from util.command.command import capture_lines, capture_text


def test_capture_text_success(mocker: MockerFixture):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = mocker.Mock(stdout="output", stderr="", returncode=0)

    result = capture_text(["echo", "hello"])

    assert result.stdout == "output"
    mock_run.assert_called_once_with(["echo", "hello"], capture_output=True, text=True, check=True)


def test_capture_lines_success(mocker: MockerFixture):
    mocker.patch(
        "util.command.local_runner.LocalRunner.capture_text",
        return_value=mocker.Mock(stdout="line1\nline2\n"),
    )

    lines = capture_lines(["ls"])

    assert lines == ["line1", "line2"]


def test_capture_lines_failure(mocker: MockerFixture):
    mocker.patch(
        "util.command.local_runner.LocalRunner.capture_text",
        side_effect=subprocess.CalledProcessError(1, "cmd", stderr="error"),
    )

    lines = capture_lines(["bad_cmd"])

    assert lines == []


def test_capture_lines_empty(mocker: MockerFixture):
    mocker.patch(
        "util.command.local_runner.LocalRunner.capture_text",
        return_value=mocker.Mock(stdout=""),
    )

    assert not capture_lines(["ls"])
