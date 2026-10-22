from pathlib import Path
import stat

import pytest

from aibrain.cli import main
from aibrain.config import ConfigError, data_root, initialize, load_config


def test_init_preserves_configuration_goals_and_private_modes(tmp_path):
    root = tmp_path / "data"
    config = initialize(root)
    config_path = root / "config.toml"
    content = config_path.read_text().replace('timezone = "Asia/Shanghai"', 'timezone = "UTC"')
    config_path.write_text(content)
    (root / "goals.yaml").write_text("goals: []\n")
    initialize(root)
    assert config_path.read_text() == content
    assert (root / "goals.yaml").read_text() == "goals: []\n"
    assert load_config(root).timezone.key == "UTC"
    for path in [root, root / "db", root / "captures", root / "logs", root / "daily", root / "bin"]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for path in [config_path, config.db_path, root / "goals.yaml"]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_config_does_not_overwrite(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    config = root / "config.toml"
    config.write_text("not valid = [")
    with pytest.raises(ConfigError):
        initialize(root)
    assert config.read_text() == "not valid = ["
    assert not (root / "db/aibrain.sqlite").exists()


@pytest.mark.parametrize("old,new", [
    ('timezone = "Asia/Shanghai"', 'timezone = "Invalid/Zone"'),
    ('max_assistant_chars = 4000', 'max_assistant_chars = -1'),
    ('ask_note = true', 'ask_note = "yes"'),
    ('enabled = ["chrome", "arc", "safari"]', 'enabled = ["unknown"]'),
    ('author_emails = []', 'author_emails = [123]'),
])
def test_config_validation(tmp_path, old, new):
    root = tmp_path / "data"
    initialize(root)
    path = root / "config.toml"
    path.write_text(path.read_text().replace(old, new))
    with pytest.raises(ConfigError):
        load_config(root)


def test_data_dir_mismatch_and_repo_guard(tmp_path):
    config = initialize(tmp_path / "data")
    path = config.root / "config.toml"
    path.write_text(path.read_text().replace(str(config.root), str(tmp_path / "other")))
    with pytest.raises(ConfigError):
        load_config(config.root)
    with pytest.raises(ConfigError):
        data_root(Path(__file__).resolve().parents[1] / "private-data")


def test_cli_data_dir_before_or_after_command_and_env(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    monkeypatch.setenv("AIBRAIN_DATA_DIR", str(tmp_path / "env-data"))
    assert main(["--data-dir", str(root), "init"]) == 0
    assert main(["init", "--data-dir", str(root)]) == 0
    assert main(["init"]) == 0
    assert (tmp_path / "env-data/config.toml").exists()
    assert main(["doctor", "--data-dir", str(tmp_path / "missing")]) == 2
    assert "Traceback" not in capsys.readouterr().err
