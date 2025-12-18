"""Spotify skill implementation for Private Assistant ecosystem.

This module provides voice-controlled Spotify integration including playback control,
playlist management, device switching, and volume control through intent-based commands.
"""

import asyncio
import logging
from dataclasses import dataclass

import aiomqtt
import jinja2
import private_assistant_commons as commons
import spotipy
from private_assistant_commons import IntentRequest, IntentType
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy.ext.asyncio import AsyncEngine

from private_assistant_spotify_skill import models

# AIDEV-NOTE: Volume limit for hearing protection - never exceed this value
MAX_VOLUME_LIMIT = 90


@dataclass
class SpotifySkillDependencies:
    """Container for SpotifySkill dependencies to reduce constructor parameter count.

    Groups related dependencies into a single object to simplify dependency injection
    and reduce the number of constructor parameters in SpotifySkill.

    Attributes:
        db_engine: Async SQLAlchemy engine for database operations.
        template_env: Jinja2 environment for response template rendering.
        sp_oauth: Configured Spotify OAuth manager for API authentication.
    """

    db_engine: AsyncEngine
    template_env: jinja2.Environment
    sp_oauth: SpotifyOAuth


class Parameters(BaseModel):
    """Parameter container for command processing.

    Encapsulates extracted parameters from voice commands including
    target devices, playlists, and volume levels.

    Attributes:
        playlist_index: 1-based index of playlist in user's playlists.
        playlists: Cached list of user's Spotify playlists.
        devices: List of available Spotify devices.
        target_device: Target device for playback operations.
        volume: Target volume level (0-100) for volume commands.
        current_room: Room where the request originated.
        is_resume: Whether this is a resume/continue operation.
    """

    playlist_index: int | None = None
    playlists: list[dict[str, str]] = []
    devices: list[models.SpotifyDevice] = []
    target_device: models.SpotifyDevice | None = None
    volume: int | None = None
    current_room: str = ""
    is_resume: bool = False


class SpotifySkill(commons.BaseSkill):
    """Main Spotify skill implementation for voice-controlled music playback.

    Provides comprehensive Spotify integration including playlist management,
    device control, playback operations, and volume adjustment through intent-based commands.
    Uses the global device registry for device management and Redis for OAuth caching.

    Attributes:
        sp: Spotify API client instance with OAuth authentication.
        db_engine: Async database engine for persistence.
        template_env: Jinja2 environment for response generation.
        intent_to_template: Mapping of intent types to response templates.
    """

    def __init__(
        self,
        config_obj: commons.SkillConfig,
        mqtt_client: aiomqtt.Client,
        dependencies: SpotifySkillDependencies,
        task_group: asyncio.TaskGroup,
        logger: logging.Logger,
    ) -> None:
        """Initialize the Spotify skill with required dependencies.

        Args:
            config_obj: Skill configuration including Spotify credentials.
            mqtt_client: MQTT client for ecosystem communication.
            dependencies: Injected dependencies (database, templates, OAuth).
            task_group: AsyncIO task group for background operations.
            logger: Logger instance for skill operations.
        """
        super().__init__(
            config_obj=config_obj,
            mqtt_client=mqtt_client,
            task_group=task_group,
            engine=dependencies.db_engine,
            logger=logger,
        )

        self.sp = spotipy.Spotify(auth_manager=dependencies.sp_oauth)
        self.db_engine = dependencies.db_engine
        self.template_env = dependencies.template_env

        # AIDEV-NOTE: Intent-based configuration replaces calculate_certainty method
        self.supported_intents = {
            IntentType.MEDIA_PLAY: 0.8,
            IntentType.MEDIA_STOP: 0.8,
            IntentType.MEDIA_NEXT: 0.8,
            IntentType.MEDIA_VOLUME_SET: 0.8,
            IntentType.QUERY_LIST: 0.7,
            IntentType.SYSTEM_HELP: 0.7,
        }

        # AIDEV-NOTE: Device type for global registry
        self.supported_device_types = ["spotify_device"]

        # AIDEV-NOTE: In-memory playlist cache - devices come from global registry
        self._playlists_cache: list[dict[str, str]] = []

        # AIDEV-NOTE: Template preloading at init prevents runtime template lookup failures
        self.intent_to_template: dict[IntentType | str, jinja2.Template] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load and validate all required templates with fallback handling.

        Raises:
            RuntimeError: If critical templates cannot be loaded.
        """
        template_mappings: dict[IntentType | str, str] = {
            IntentType.SYSTEM_HELP: "help.j2",
            IntentType.MEDIA_PLAY: "playback_started.j2",
            IntentType.MEDIA_STOP: "playback_stopped.j2",
            IntentType.MEDIA_NEXT: "next_track.j2",
            IntentType.MEDIA_VOLUME_SET: "set_volume.j2",
            "list_playlists": "list_playlists.j2",
            "list_devices": "list_devices.j2",
            "continue": "continue.j2",
        }

        failed_templates = []
        for key, template_name in template_mappings.items():
            try:
                self.intent_to_template[key] = self.template_env.get_template(template_name)
            except jinja2.TemplateNotFound as e:
                self.logger.error("Failed to load template %s: %s", template_name, e)
                failed_templates.append(template_name)

        if failed_templates:
            raise RuntimeError(f"Critical templates failed to load: {', '.join(failed_templates)}")

        self.logger.debug("All templates successfully loaded during initialization.")

    @property
    def playlists(self) -> list[dict[str, str]]:
        """Get cached playlists."""
        return self._playlists_cache

    def _get_spotify_devices(self) -> list[models.SpotifyDevice]:
        """Get Spotify devices from global device registry.

        Returns:
            List of SpotifyDevice objects from the global registry.
        """
        devices = []
        for global_device in self.global_devices:
            if global_device.device_type and global_device.device_type.name == "spotify_device":
                devices.append(models.SpotifyDevice.from_global_device(global_device))
        return devices

    async def skill_preparations(self) -> None:
        """Perform skill preparations including device sync.

        CRITICAL: Must call super().skill_preparations() to register skill
        and device types with the global registry.
        """
        await super().skill_preparations()
        await self._sync_spotify_devices()
        await self._refresh_playlists()
        self.logger.info(
            "Skill preparations complete. %d devices loaded, %d playlists cached.",
            len(self._get_spotify_devices()),
            len(self._playlists_cache),
        )

    async def _refresh_playlists(self) -> None:
        """Refresh the in-memory playlist cache from Spotify API."""
        try:
            playlists_response = await asyncio.to_thread(self.sp.current_user_playlists)
            # AIDEV-NOTE: Sort by ID for consistent ordering in UI responses
            self._playlists_cache = sorted(playlists_response.get("items", []), key=lambda x: x["id"])
            self.logger.debug("Playlist cache refreshed with %d playlists", len(self._playlists_cache))
        except Exception as e:
            self.logger.error("Failed to refresh playlist cache: %s", e)

    async def _sync_spotify_devices(self) -> None:
        """Sync Spotify devices to global device registry.

        Fetches available devices from Spotify API and registers them
        in the global device registry. Device names should follow the
        format 'room-devicename' for automatic room association.
        """
        try:
            spotify_devices_response = await asyncio.to_thread(self.sp.devices)
            spotify_devices = spotify_devices_response.get("devices", [])

            for device in spotify_devices:
                try:
                    # AIDEV-NOTE: Parse room-name format for automatic room association
                    room, name = device["name"].split("-", 1)
                    room = room.replace("_", "")

                    await self.register_device(
                        device_type="spotify_device",
                        name=name,
                        pattern=[name.lower(), device["name"].lower()],
                        room=room,
                        device_attributes={
                            "spotify_id": device["id"],
                            "is_main": False,
                            "default_volume": 55,
                        },
                    )
                    self.logger.debug("Registered Spotify device: %s in room %s", name, room)
                except ValueError:
                    self.logger.warning("Device name format invalid (expected 'room-name'): %s", device["name"])

            self.logger.info("Synced %d Spotify devices to global registry", len(spotify_devices))
        except Exception as e:
            self.logger.error("Failed to sync Spotify devices: %s", e)

    def _get_main_device(self, room: str) -> models.SpotifyDevice | None:
        """Find the main device for a specific room.

        Args:
            room: Room name to search for.

        Returns:
            Main SpotifyDevice for the room or first device in room if no main set.
        """
        devices = self._get_spotify_devices()

        # First try to find a device marked as main
        for device in devices:
            if device.is_main and device.room == room:
                return device

        # Fall back to first device in the room
        for device in devices:
            if device.room == room:
                return device

        return None

    def _get_device_by_index(self, index: int) -> models.SpotifyDevice | None:
        """Get device by 1-based index.

        Args:
            index: 1-based device index from voice command.

        Returns:
            SpotifyDevice or None if index is invalid.
        """
        devices = self._get_spotify_devices()
        try:
            return devices[index - 1]
        except IndexError:
            self.logger.error("Invalid device index: %d", index)
            return None

    def _get_playlist_id_by_index(self, index: int) -> str | None:
        """Get Spotify playlist ID by 1-based index.

        Args:
            index: 1-based playlist index from voice command.

        Returns:
            Spotify playlist ID string or None if index is invalid.
        """
        try:
            return self.playlists[index - 1]["id"]
        except IndexError:
            self.logger.error("Invalid playlist index: %d", index)
            return None

    def _render_response(self, template_key: IntentType | str, parameters: Parameters) -> str:
        """Render response using template for given intent type.

        Args:
            template_key: The intent type or string key to render response for.
            parameters: Command parameters for template context.

        Returns:
            Rendered response text.
        """
        template = self.intent_to_template.get(template_key)
        if template:
            return template.render(
                intent_type=template_key,
                parameters=parameters,
            )
        self.logger.error("No template found for key: %s", template_key)
        return "Sorry, I couldn't process your request."

    async def process_request(self, intent_request: IntentRequest) -> None:
        """Main request processing method - routes intent to appropriate handler.

        Orchestrates the full command processing pipeline:
        1. Extract intent type from classified intent
        2. Route to appropriate intent handler
        3. Handler extracts entities, controls devices, and sends response

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        classified_intent = intent_request.classified_intent
        intent_type = classified_intent.intent_type

        self.logger.debug(
            "Processing intent %s with confidence %.2f",
            intent_type,
            classified_intent.confidence,
        )

        # Route to appropriate handler
        if intent_type == IntentType.MEDIA_PLAY:
            await self._handle_media_play(intent_request)
        elif intent_type == IntentType.MEDIA_STOP:
            await self._handle_media_stop(intent_request)
        elif intent_type == IntentType.MEDIA_NEXT:
            await self._handle_media_next(intent_request)
        elif intent_type == IntentType.MEDIA_VOLUME_SET:
            await self._handle_volume_set(intent_request)
        elif intent_type == IntentType.QUERY_LIST:
            await self._handle_query_list(intent_request)
        elif intent_type == IntentType.SYSTEM_HELP:
            await self._handle_system_help(intent_request)
        else:
            self.logger.warning("Unsupported intent type: %s", intent_type)
            await self.send_response(
                "I'm not sure how to handle that request.",
                client_request=intent_request.client_request,
            )

    async def _handle_media_play(self, intent_request: IntentRequest) -> None:
        """Handle MEDIA_PLAY intent - start playlist or resume playback.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        classified_intent = intent_request.classified_intent
        client_request = intent_request.client_request
        current_room = client_request.room

        # Extract entities
        number_entities = classified_intent.entities.get("number", [])
        device_entities = classified_intent.entities.get("device", [])
        modifier_entities = classified_intent.entities.get("modifier", [])

        # Check if this is a resume/continue request
        is_resume = any(m.normalized_value.lower() in ("continue", "resume") for m in modifier_entities)

        if is_resume:
            await self._handle_continue_playback(intent_request)
            return

        # Extract playlist index from number entities
        playlist_index = None
        device_index = None
        for entity in number_entities:
            # Use metadata to determine context, or just take first number as playlist
            if playlist_index is None:
                playlist_index = int(entity.normalized_value)
            elif device_index is None:
                device_index = int(entity.normalized_value)

        # Resolve target device
        target_device = None
        if device_index:
            target_device = self._get_device_by_index(device_index)
        elif device_entities:
            # Try to find device by name
            device_name = device_entities[0].normalized_value.lower()
            for device in self._get_spotify_devices():
                if device.name.lower() == device_name:
                    target_device = device
                    break
        if not target_device:
            target_device = self._get_main_device(current_room)

        if not target_device:
            await self.send_response("I couldn't find a Spotify device to play on.", client_request)
            return

        if playlist_index is None:
            await self.send_response("Please specify which playlist to play.", client_request)
            return

        # Build parameters and send response
        parameters = Parameters(
            playlist_index=playlist_index,
            playlists=self.playlists,
            devices=self._get_spotify_devices(),
            target_device=target_device,
            current_room=current_room,
        )

        response = self._render_response(IntentType.MEDIA_PLAY, parameters)
        self.add_task(self.send_response(response, client_request=client_request))

        # Start playback
        playlist_id = self._get_playlist_id_by_index(playlist_index)
        if playlist_id:
            self.add_task(self._start_spotify_playlist(target_device, playlist_id))

    async def _handle_continue_playback(self, intent_request: IntentRequest) -> None:
        """Handle continue/resume playback command.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        client_request = intent_request.client_request
        current_room = client_request.room

        main_device = self._get_main_device(current_room)
        if not main_device:
            await self.send_response(f"No Spotify device found in {current_room}.", client_request)
            return

        parameters = Parameters(
            target_device=main_device,
            current_room=current_room,
            is_resume=True,
            devices=self._get_spotify_devices(),
        )

        response = self._render_response("continue", parameters)
        self.add_task(self.send_response(response, client_request=client_request))

        # Execute continue action
        try:
            current_playback = await asyncio.to_thread(self.sp.current_playback)

            if current_playback and current_playback.get("is_playing"):
                current_device_id = current_playback["device"]["id"]
                if main_device.spotify_id != current_device_id:
                    # AIDEV-NOTE: Transfer active playback to room's main device
                    await asyncio.to_thread(self.sp.transfer_playback, device_id=main_device.spotify_id)
                    self.logger.info("Transferred playback to device '%s' in room '%s'", main_device.name, current_room)
            else:
                # Start/resume playback on main device
                await asyncio.to_thread(self.sp.transfer_playback, device_id=main_device.spotify_id)
                self.logger.info("Started playback on device '%s' in room '%s'", main_device.name, current_room)
        except spotipy.SpotifyException as e:
            self.logger.error("Spotify API error during continue: %s", e)

    async def _handle_media_stop(self, intent_request: IntentRequest) -> None:
        """Handle MEDIA_STOP intent - pause playback.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        client_request = intent_request.client_request

        parameters = Parameters(
            current_room=client_request.room,
            devices=self._get_spotify_devices(),
        )

        response = self._render_response(IntentType.MEDIA_STOP, parameters)
        self.add_task(self.send_response(response, client_request=client_request))

        try:
            await asyncio.to_thread(self.sp.pause_playback)
            self.logger.info("Playback paused.")
        except spotipy.SpotifyException as e:
            self.logger.error("Spotify API error during stop: %s", e)

    async def _handle_media_next(self, intent_request: IntentRequest) -> None:
        """Handle MEDIA_NEXT intent - skip to next track.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        client_request = intent_request.client_request

        parameters = Parameters(
            current_room=client_request.room,
            devices=self._get_spotify_devices(),
        )

        response = self._render_response(IntentType.MEDIA_NEXT, parameters)
        self.add_task(self.send_response(response, client_request=client_request))

        try:
            await asyncio.to_thread(self.sp.next_track)
            self.logger.info("Skipped to next track.")
        except spotipy.SpotifyException as e:
            self.logger.error("Spotify API error during next track: %s", e)

    async def _handle_volume_set(self, intent_request: IntentRequest) -> None:
        """Handle MEDIA_VOLUME_SET intent - set volume level.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        classified_intent = intent_request.classified_intent
        client_request = intent_request.client_request

        # Extract volume from number entities
        number_entities = classified_intent.entities.get("number", [])
        volume = None
        if number_entities:
            volume = int(number_entities[0].normalized_value)

        if volume is None:
            await self.send_response("Please specify the volume level.", client_request)
            return

        # AIDEV-NOTE: Critical safety limit - never exceed MAX_VOLUME_LIMIT
        final_volume = min(volume, MAX_VOLUME_LIMIT)

        parameters = Parameters(
            volume=final_volume,
            current_room=client_request.room,
            devices=self._get_spotify_devices(),
        )

        response = self._render_response(IntentType.MEDIA_VOLUME_SET, parameters)
        self.add_task(self.send_response(response, client_request=client_request))

        try:
            await asyncio.to_thread(self.sp.volume, volume_percent=final_volume)
            self.logger.info("Spotify volume set to %d%%", final_volume)
        except spotipy.SpotifyException as e:
            self.logger.error("Spotify API error during volume set: %s", e)

    async def _handle_query_list(self, intent_request: IntentRequest) -> None:
        """Handle QUERY_LIST intent - list playlists or devices.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        classified_intent = intent_request.classified_intent
        client_request = intent_request.client_request

        # Determine what to list based on entities or raw text
        device_entities = classified_intent.entities.get("device", [])
        raw_text = classified_intent.raw_text.lower()

        parameters = Parameters(
            playlists=self.playlists,
            devices=self._get_spotify_devices(),
            current_room=client_request.room,
        )

        # AIDEV-NOTE: Differentiate between list playlists and list devices
        if device_entities or "device" in raw_text:
            response = self._render_response("list_devices", parameters)
        else:
            response = self._render_response("list_playlists", parameters)

        await self.send_response(response, client_request=client_request)

    async def _handle_system_help(self, intent_request: IntentRequest) -> None:
        """Handle SYSTEM_HELP intent - show available commands.

        Args:
            intent_request: The intent request with classified intent and client request.
        """
        client_request = intent_request.client_request

        parameters = Parameters(
            current_room=client_request.room,
            devices=self._get_spotify_devices(),
        )

        response = self._render_response(IntentType.SYSTEM_HELP, parameters)
        await self.send_response(response, client_request=client_request)

    async def _start_spotify_playlist(self, device: models.SpotifyDevice, playlist_id: str) -> None:
        """Start playlist playback on a specific device with optimal settings.

        Initiates playlist playback, waits for device activation, then applies
        the device's default volume and enables shuffle mode.

        Args:
            device: Target SpotifyDevice for playback.
            playlist_id: Spotify playlist ID to play.
        """
        try:
            await asyncio.to_thread(
                self.sp.start_playback,
                device_id=device.spotify_id,
                context_uri=f"spotify:playlist:{playlist_id}",
            )
            # AIDEV-NOTE: Critical timing - device needs activation time before volume/shuffle
            await asyncio.sleep(3.0)
            await asyncio.to_thread(self.sp.volume, volume_percent=device.default_volume)
            await asyncio.to_thread(self.sp.shuffle, state=True)
            self.logger.info("Started playlist '%s' on device '%s'", playlist_id, device.name)
        except spotipy.SpotifyException as e:
            self.logger.error("Failed to start playlist '%s' on device '%s': %s", playlist_id, device.name, e)
        except Exception as e:
            self.logger.error(
                "Unexpected error while starting playlist '%s' on device '%s': %s",
                playlist_id,
                device.name,
                e,
                exc_info=True,
            )
