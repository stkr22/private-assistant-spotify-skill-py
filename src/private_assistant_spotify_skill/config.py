"""Configuration management for the Spotify skill.

This module extends the base skill configuration with Spotify-specific settings.
"""

import logging

import private_assistant_commons as commons

logger = logging.getLogger(__name__)


class SkillConfig(commons.SkillConfig):
    """Configuration class for Spotify skill settings.

    Extends the base SkillConfig with Spotify API credentials and OAuth settings.
    All sensitive credentials should be provided via environment variables or
    secure configuration management.

    Attributes:
        spotify_client_id: Spotify application client ID from developer dashboard.
        spotify_client_secret: Spotify application client secret.
        redirect_uri: OAuth redirect URI configured in Spotify app settings.
        scope: Space-separated Spotify API scopes required for skill functionality.
    """

    spotify_client_id: str
    spotify_client_secret: str
    redirect_uri: str
    scope: str = "user-read-playback-state user-modify-playback-state playlist-read-private"
