from pathlib import Path

import pytest

from ai_agent_launcher._config import default_config_path, load_config
from ai_agent_launcher._errors import ConfigError
from ai_agent_launcher._models import AgentId


def test_missing_default_configuration_uses_empty_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    config = load_config(None, (AgentId("codex"),))

    assert default_config_path() == tmp_path / "config" / "ai-agent-launcher" / "config.toml"
    assert config.core.writable_dirs == ()
    assert config.core.launcher_directory is None
    assert config.agent_settings == {}


def test_configuration_parses_core_and_selected_agent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[core]
writable_dirs = ["/tmp/one"]
launcher_directory = "/tmp/launchers"

[agents.codex]
model = "test-model"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path, (AgentId("codex"),))

    assert config.core.writable_dirs == ("/tmp/one",)
    assert config.core.launcher_directory == Path("/tmp/launchers")
    assert config.agent_settings[AgentId("codex")] == {"model": "test-model"}


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("[core\nwritable_dirs = []", "invalid TOML"),
        ("unknown = true", "unknown configuration"),
        ("[core]\nwritable_dirs = [1]", "array of strings"),
        ('[core]\nlauncher_directory = "relative"', "absolute path"),
        ('[agents.claude]\nmodel = "x"', "unsupported agent"),
    ],
)
def test_configuration_rejects_invalid_values(tmp_path: Path, contents: str, message: str) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(config_path, (AgentId("codex"),))


def test_explicit_missing_configuration_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "missing.toml", (AgentId("codex"),))
