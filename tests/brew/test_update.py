import pytest
from pytest_mock import MockerFixture

from brew.update import update


def test_dry_run_makes_no_brew_calls(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["brew-update", "--dry-run"])
    mock_capture_text = mocker.patch("brew.update.capture_text")
    mock_capture_lines = mocker.patch("brew.update.capture_lines")
    mock_run = mocker.patch("brew.update.subprocess.run")

    update()

    mock_capture_text.assert_not_called()
    mock_capture_lines.assert_not_called()
    mock_run.assert_not_called()
    assert "[dry-run]" in capsys.readouterr().out


def test_help_exits_cleanly_without_brew_calls(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setattr("sys.argv", ["brew-update", "--help"])
    mock_capture_text = mocker.patch("brew.update.capture_text")

    with pytest.raises(SystemExit) as error:
        update()

    assert error.value.code == 0
    mock_capture_text.assert_not_called()
