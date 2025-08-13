"""Database models for the Spotify skill.

This module defines SQLModel classes for database persistence.
"""

from sqlmodel import Field, SQLModel


class TokenCache(SQLModel, table=True):
    """Database model for storing Spotify OAuth tokens.

    Used by Spotipy's cache handler to maintain authentication state
    across application restarts in a stateless deployment environment.

    Attributes:
        id: Primary key for the token record.
        token: JSON string containing the OAuth token data.
    """

    id: int | None = Field(default=None, primary_key=True)
    token: str


class Device(SQLModel, table=True):
    """Database model for Spotify device management.

    Represents a Spotify-compatible device with room association
    and playback preferences. Devices are discovered from Spotify API
    and enhanced with room-specific metadata.

    Attributes:
        id: Primary key for the device record.
        spotify_id: Unique identifier from Spotify API.
        name: Human-readable device name (parsed from Spotify device name).
        room: Room location (parsed from device name format 'room-name').
        is_main: Whether this device is the primary device for its room.
        default_volume: Default volume level (0-100) for this device.
        ip: Optional IP address for direct device communication.
    """

    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str
    name: str
    room: str
    is_main: bool = False
    default_volume: int = 55
    ip: str | None = None
