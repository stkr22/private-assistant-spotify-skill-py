"""Configuration management for the Spotify skill.

This module extends the base skill configuration with Spotify-specific settings.
Uses pydantic-settings with env_prefix for secure environment variable configuration.
"""

import private_assistant_commons as commons
from pydantic import Field
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


class RedisSettings(BaseSettings):
    """Redis connection settings for OAuth token caching.

    Environment variables (with REDIS_ prefix):
        REDIS_HOST: Redis server hostname (default: localhost).
        REDIS_PORT: Redis server port (default: 6379).
        REDIS_PASSWORD: Redis password (optional, default: None).
        REDIS_DB: Redis database number (default: 0).
    """

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0

    @property
    def url(self) -> str:
        """Build Redis connection URL from components."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class SkillConfig(commons.SkillConfig):
    """Configuration class for Spotify skill settings.

    Combines base skill configuration with Spotify and Redis settings.
    Spotify and Redis credentials are loaded from environment variables
    with their respective prefixes (SPOTIFY_, REDIS_).

    Attributes:
        spotify: Spotify API credentials and OAuth settings.
        redis: Redis connection settings for token caching.
    """

    # AIDEV-NOTE: Using default_factory to delay instantiation until SkillConfig is created,
    # avoiding import-time validation errors when env vars are not yet set.
    spotify: SpotifySettings = Field(default_factory=lambda: SpotifySettings())
    redis: RedisSettings = Field(default_factory=lambda: RedisSettings())
