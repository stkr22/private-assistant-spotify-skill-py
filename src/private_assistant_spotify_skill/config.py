"""Configuration management for the Spotify skill.

This module extends the base skill configuration with Spotify-specific settings.
Uses pydantic-settings with env_prefix for secure environment variable configuration.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class SpotifySettings(BaseSettings):
    """Spotify API credentials and OAuth settings.

    Environment variables (with SPOTIFY_ prefix):
        SPOTIFY_CLIENT_ID: Application client ID from Spotify developer dashboard.
        SPOTIFY_CLIENT_SECRET: Application client secret.
        SPOTIFY_REDIRECT_URI: OAuth redirect URI configured in Spotify app settings.
        SPOTIFY_SCOPE: Space-separated API scopes required for skill functionality.
    """

    model_config = SettingsConfigDict(env_prefix="SPOTIFY_")

    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str = "user-read-playback-state user-modify-playback-state playlist-read-private"


class ValkeySettings(BaseSettings):
    """Valkey connection settings for OAuth token caching.

    Environment variables (with VALKEY_ prefix):
        VALKEY_HOST: Valkey server hostname (required).
        VALKEY_PORT: Valkey server port (default: 6379).
        VALKEY_USERNAME: Valkey username for ACL auth (optional).
        VALKEY_PASSWORD: Valkey password (optional).
        VALKEY_DB: Valkey database number (default: 0).
    """

    model_config = SettingsConfigDict(env_prefix="VALKEY_")

    host: str
    port: int = 6379
    username: str | None = None
    password: str | None = None
    db: int = 0


# AIDEV-NOTE: SkillConfig is now imported directly from commons
# Spotify and Valkey settings are initialized separately in main.py
