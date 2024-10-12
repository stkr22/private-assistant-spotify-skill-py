import pathlib

import pytest
import yaml
from pydantic import ValidationError

from private_assistant_spotify_skill.config import (
    SkillConfig,
)

# Sample invalid YAML configuration (missing required fields)
invalid_yaml = """
mqtt_server_host: "test_host"
mqtt_server_port: "invalid_port"  # invalid type
client_id: 12345  # invalid type
"""


def test_load_valid_config():
    data_directory = pathlib.Path(__file__).parent / "data" / "config.yaml"
    with data_directory.open("r") as file:
        config_data = yaml.safe_load(file)
    config = SkillConfig.model_validate(config_data)

    assert config.spotify_client_id == "dfssgrz53trgsr"
    assert config.spotify_client_secret == "dsfsat4watwa4tsgsr"
    assert config.redirect_uri == "http://localhost"
    assert config.scope == "user-read-playback-state user-modify-playback-state"


def test_load_invalid_config():
    config_data = yaml.safe_load(invalid_yaml)
    with pytest.raises(ValidationError):
        SkillConfig.model_validate(config_data)
