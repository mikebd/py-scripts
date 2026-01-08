from pytest_mock import MockerFixture

from brew.sync import brew_list_manually_installed_formulas
from util.command.ssh_runner import SshRunner


def test_brew_list_manually_installed_formulas_local(mocker: MockerFixture):
    mock_capture_lines = mocker.patch(
        "brew.sync.capture_lines", return_value=["formula1", "formula2"]
    )

    result = brew_list_manually_installed_formulas()

    assert result == {"formula1", "formula2"}
    mock_capture_lines.assert_called_once_with(
        ["brew", "list", "--formula", "--installed-on-request"]
    )


def test_brew_list_manually_installed_formulas_remote(mocker: MockerFixture):
    mock_capture_lines = mocker.patch(
        "brew.sync.capture_lines", return_value=["remote1", "remote2"]
    )
    runner = SshRunner(host="remote-host")

    result = brew_list_manually_installed_formulas(runner=runner)

    assert result == {"remote1", "remote2"}
    # Check that SshRunner was used
    args, kwargs = mock_capture_lines.call_args
    assert args[0] == [
        "/home/linuxbrew/.linuxbrew/bin/brew",
        "list",
        "--formula",
        "--installed-on-request",
    ]
    assert kwargs["runner"] == runner
