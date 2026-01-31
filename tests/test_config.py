import os

import pytest
from pydantic import ValidationError

from private_assistant_spotify_skill.config import (
    SpotifySettings,
    ValkeySettings,
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
        """Test that RedisSettings loads from VALKEY_ prefixed env vars."""
        monkeypatch.setenv("VALKEY_HOST", "redis-server")
        monkeypatch.setenv("VALKEY_PORT", "6380")
        monkeypatch.setenv("VALKEY_PASSWORD", "secret")
        monkeypatch.setenv("VALKEY_DB", "1")

        settings = ValkeySettings()

        assert settings.host == "redis-server"
        assert settings.port == 6380
        assert settings.password == "secret"
        assert settings.db == 1

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that RedisSettings has sensible defaults for optional fields."""
        # Clear any existing VALKEY_ env vars except HOST (which is required)
        for key in list(os.environ.keys()):
            if key.startswith("VALKEY_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("VALKEY_HOST", "localhost")

        settings = ValkeySettings()

        assert settings.host == "localhost"
        assert settings.port == 6379
        assert settings.username is None
        assert settings.password is None
        assert settings.db == 0

    def test_valkey_settings_with_all_parameters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ValkeySettings with all parameters including ACL auth."""
        monkeypatch.setenv("VALKEY_HOST", "redis-server")
        monkeypatch.setenv("VALKEY_PORT", "6380")
        monkeypatch.setenv("VALKEY_USERNAME", "default")
        monkeypatch.setenv("VALKEY_PASSWORD", "secret")
        monkeypatch.setenv("VALKEY_DB", "2")

        settings = ValkeySettings()

        assert settings.host == "redis-server"
        assert settings.port == 6380
        assert settings.username == "default"
        assert settings.password == "secret"
        assert settings.db == 2
