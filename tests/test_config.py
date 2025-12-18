import os
import pathlib

import pytest
import yaml
from pydantic import ValidationError

from private_assistant_spotify_skill.config import (
    RedisSettings,
    SkillConfig,
    SpotifySettings,
)


class TestSpotifySettings:
    """Test SpotifySettings with environment variables."""

    def test_load_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that SpotifySettings loads from SPOTIFY_ prefixed env vars."""
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_client_secret")
        monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback")
        monkeypatch.setenv("SPOTIFY_SCOPE", "user-read-playback-state")

        settings = SpotifySettings()

        assert settings.client_id == "test_client_id"
        assert settings.client_secret == "test_client_secret"
        assert settings.redirect_uri == "http://localhost:8080/callback"
        assert settings.scope == "user-read-playback-state"

    def test_default_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that scope has a sensible default value."""
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_client_secret")
        monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback")
        # Don't set SPOTIFY_SCOPE - use default

        settings = SpotifySettings()

        assert "user-read-playback-state" in settings.scope
        assert "user-modify-playback-state" in settings.scope

    def test_missing_required_fields_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing required fields raise ValidationError."""
        # Clear any existing SPOTIFY_ env vars
        for key in list(os.environ.keys()):
            if key.startswith("SPOTIFY_"):
                monkeypatch.delenv(key, raising=False)

        with pytest.raises(ValidationError):
            SpotifySettings()


class TestRedisSettings:
    """Test RedisSettings with environment variables."""

    def test_load_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that RedisSettings loads from REDIS_ prefixed env vars."""
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "secret")
        monkeypatch.setenv("REDIS_DB", "1")

        settings = RedisSettings()

        assert settings.host == "redis-server"
        assert settings.port == 6380  # noqa: PLR2004
        assert settings.password == "secret"
        assert settings.db == 1

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that RedisSettings has sensible defaults for optional fields."""
        # Clear any existing REDIS_ env vars except HOST (which is required)
        for key in list(os.environ.keys()):
            if key.startswith("REDIS_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("REDIS_HOST", "localhost")

        settings = RedisSettings()

        assert settings.host == "localhost"
        assert settings.port == 6379  # noqa: PLR2004
        assert settings.username is None
        assert settings.password is None
        assert settings.db == 0

    def test_url_property_without_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test URL property generates correct URL without password."""
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_DB", "2")
        for key in ["REDIS_PASSWORD"]:
            monkeypatch.delenv(key, raising=False)

        settings = RedisSettings()

        assert settings.url == "redis://redis-server:6380/2"

    def test_url_property_with_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test URL property generates correct URL with password only."""
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "secret")
        monkeypatch.setenv("REDIS_DB", "2")
        monkeypatch.delenv("REDIS_USERNAME", raising=False)

        settings = RedisSettings()

        assert settings.url == "redis://:secret@redis-server:6380/2"

    def test_url_property_with_username_and_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test URL property generates correct URL with username and password (ACL auth)."""
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_USERNAME", "default")
        monkeypatch.setenv("REDIS_PASSWORD", "secret")
        monkeypatch.setenv("REDIS_DB", "2")

        settings = RedisSettings()

        assert settings.url == "redis://default:secret@redis-server:6380/2"


class TestSkillConfig:
    """Test SkillConfig combining base config with nested settings."""

    def test_load_valid_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading valid YAML config with env var settings."""
        # Set required Spotify env vars
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_client_secret")
        monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback")
        # Set required Redis env vars
        monkeypatch.setenv("REDIS_HOST", "localhost")

        data_directory = pathlib.Path(__file__).parent / "data" / "config.yaml"
        with data_directory.open("r") as file:
            config_data = yaml.safe_load(file)

        config = SkillConfig.model_validate(config_data)

        # Base config from YAML
        assert config.client_id == "test_spotify_skill"
        assert config.mqtt_server_host == "localhost"
        assert config.mqtt_server_port == 1883  # noqa: PLR2004

        # Nested settings from env vars
        assert config.spotify.client_id == "test_client_id"
        assert config.redis.host == "localhost"

    def test_load_invalid_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that invalid YAML config raises ValidationError."""
        # Set required Spotify env vars so nested settings don't fail
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_client_secret")
        monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback")
        # Set required Redis env vars
        monkeypatch.setenv("REDIS_HOST", "localhost")

        invalid_yaml = """
mqtt_server_host: "test_host"
mqtt_server_port: "invalid_port"
client_id: 12345
"""
        config_data = yaml.safe_load(invalid_yaml)
        with pytest.raises(ValidationError):
            SkillConfig.model_validate(config_data)
