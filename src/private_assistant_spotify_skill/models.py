"""Database models and helpers for the Spotify skill.

This module provides helper classes for working with Spotify devices
from the global device registry.
"""

from private_assistant_commons.database import GlobalDevice
from pydantic import BaseModel


class SpotifyDevice(BaseModel):
    """Helper class for Spotify device data extracted from GlobalDevice.

    Provides a convenient interface for accessing Spotify-specific device
    attributes stored in the global device registry.

    Attributes:
        global_device: Reference to the underlying GlobalDevice.
        spotify_id: Spotify API device identifier.
        name: Device display name.
        room: Room where the device is located.
        is_main: Whether this is the primary device for the room.
        default_volume: Default playback volume (0-100).

    """

    global_device: GlobalDevice
    spotify_id: str
    name: str
    room: str
    is_main: bool = False
    default_volume: int = 55

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_global_device(cls, global_device: GlobalDevice) -> "SpotifyDevice":
        """Create a SpotifyDevice from a GlobalDevice.

        Args:
            global_device: The GlobalDevice from the registry.

        Returns:
            SpotifyDevice with extracted attributes.

        """
        attrs = global_device.device_attributes or {}
        return cls(
            global_device=global_device,
            spotify_id=attrs.get("spotify_id", ""),
            name=global_device.name,
            room=global_device.room.name if global_device.room else "",
            is_main=attrs.get("is_main", False),
            default_volume=attrs.get("default_volume", 55),
        )
