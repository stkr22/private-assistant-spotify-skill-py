"""Spotify skill implementation for Private Assistant ecosystem.

This module provides voice-controlled Spotify integration including playback control,
playlist management, device switching, and volume control through natural language commands.
"""

import asyncio
import enum
import logging
import string

import aiomqtt
import jinja2
import private_assistant_commons as commons
import spotipy
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from private_assistant_spotify_skill import config, models

# AIDEV-NOTE: Volume limit for hearing protection - never exceed this value
MAX_VOLUME_LIMIT = 90


class Parameters(BaseModel):
    """Parameter container for command processing.

    Encapsulates extracted parameters from voice commands including
    target devices, playlists, and volume levels. Used to pass
    structured data between command parsing and execution phases.

    Attributes:
        playlist_id: 1-based index of playlist in user's playlists.
        device_id: 1-based index of device in available devices.
        playlists: Cached list of user's Spotify playlists.
        devices: Cached list of available Spotify devices.
        volume: Target volume level (0-100) for volume commands.
    """

    playlist_id: int | None = None
    device_id: int | None = None
    playlists: list[dict[str, str]] = []
    devices: list[models.Device] = []
    volume: int | None = None


class Action(enum.Enum):
    """Enumeration of supported voice commands.

    Each action maps to a list of keywords that must all be present
    in the voice command for a match. The matching algorithm uses
    set intersection to ensure all required keywords are found.
    """

    HELP = ["help"]  # noqa: RUF012
    LIST_PLAYLISTS = ["list", "playlists"]  # noqa: RUF012
    LIST_DEVICES = ["list", "devices"]  # noqa: RUF012
    PLAY_PLAYLIST = ["play", "playlist"]  # noqa: RUF012
    STOP_PLAYBACK = ["stop", "playback"]  # noqa: RUF012
    NEXT_TRACK = ["next", "track"]  # noqa: RUF012
    SET_VOLUME = ["set", "volume"]  # noqa: RUF012
    CONTINUE = ["continue"]  # noqa: RUF012

    @classmethod
    def find_matching_action(cls, text: str) -> "Action | None":
        """Find the matching action for a given text command.

        Uses keyword matching to identify the intended action from voice input.
        All keywords for an action must be present in the text for a match.

        Args:
            text: Raw voice command text to analyze.

        Returns:
            Matching Action enum value or None if no match found.
        """
        # AIDEV-NOTE: Remove punctuation to improve keyword matching reliability
        text = text.translate(str.maketrans("", "", string.punctuation))
        text_words = set(text.lower().split())

        for action in cls:
            if all(word in text_words for word in action.value):
                return action
        return None


class SpotifySkill(commons.BaseSkill):
    """Main Spotify skill implementation for voice-controlled music playback.

    Provides comprehensive Spotify integration including playlist management,
    device control, playback operations, and volume adjustment through voice commands.
    Uses async operations with caching for optimal performance.

    Attributes:
        sp: Spotify API client instance with OAuth authentication.
        db_engine: Async database engine for device and token management.
        action_to_answer: Mapping of actions to Jinja2 response templates.
        template_env: Jinja2 environment for response generation.
    """

    def __init__(  # noqa: PLR0913
        self,
        config_obj: config.SkillConfig,
        mqtt_client: aiomqtt.Client,
        template_env: jinja2.Environment,
        sp_oauth: spotipy.SpotifyOAuth,
        db_engine: AsyncEngine,
        task_group: asyncio.TaskGroup,
        logger: logging.Logger,
    ) -> None:
        """Initialize the Spotify skill with required dependencies.

        Args:
            config_obj: Skill configuration including Spotify credentials.
            mqtt_client: MQTT client for ecosystem communication.
            template_env: Jinja2 environment for response templates.
            sp_oauth: Configured Spotify OAuth manager.
            db_engine: Async database engine for persistence.
            task_group: AsyncIO task group for background operations.
            logger: Logger instance for skill operations.
        """
        super().__init__(config_obj, mqtt_client, task_group, logger=logger)
        self.sp = spotipy.Spotify(auth_manager=sp_oauth)
        self.db_engine = db_engine
        self.task_group = task_group

        # AIDEV-NOTE: Template mapping for action responses - add new templates here
        self.action_to_answer: dict[Action, jinja2.Template] = {
            Action.HELP: template_env.get_template("help.j2"),
            Action.LIST_PLAYLISTS: template_env.get_template("list_playlists.j2"),
            Action.LIST_DEVICES: template_env.get_template("list_devices.j2"),
            Action.PLAY_PLAYLIST: template_env.get_template("playback_started.j2"),
            Action.STOP_PLAYBACK: template_env.get_template("playback_stopped.j2"),
            Action.NEXT_TRACK: template_env.get_template("next_track.j2"),
            Action.SET_VOLUME: template_env.get_template("set_volume.j2"),
            Action.CONTINUE: template_env.get_template("continue.j2"),
        }
        self.template_env = template_env

        # AIDEV-NOTE: In-memory caches for performance - refreshed periodically
        self._playlists_cache: list[dict[str, str]] = []
        self._devices_cache: list[models.Device] = []
        self.add_task(self._refresh_cache())

    @property
    def playlists(self) -> list[dict[str, str]]:
        return self._playlists_cache

    @property
    def devices(self) -> list[models.Device]:
        return self._devices_cache

    async def _refresh_cache(self) -> None:
        """Refresh the in-memory caches for playlists and devices.

        Fetches current user playlists and available devices from Spotify API.
        For devices, parses the naming convention 'room-name' and creates/updates
        database entries with room associations. Runs as a background task.

        Note:
            Device name format must be 'room-devicename' for proper room association.
            Devices with invalid names are logged and skipped.
        """
        try:
            # AIDEV-NOTE: Sort by ID for consistent ordering in UI responses
            self._playlists_cache = sorted(self.sp.current_user_playlists()["items"], key=lambda x: x["id"])
            self._devices_cache = []
            spotify_devices = sorted(self.sp.devices()["devices"], key=lambda x: x["id"])

            async with AsyncSession(self.db_engine) as session:
                for device in spotify_devices:
                    existing_device = (
                        await session.exec(select(models.Device).where(models.Device.spotify_id == device["id"]))
                    ).first()
                    if not existing_device:
                        try:
                            # AIDEV-NOTE: Parse room-name format for automatic room association
                            room, name = device["name"].split("-", 1)
                            new_device = models.Device(spotify_id=device["id"], name=name, room=room.replace("_", ""))
                            session.add(new_device)
                            self._devices_cache.append(models.Device.model_validate(new_device.model_dump()))
                        except ValueError:
                            self.logger.error("Device name is broken, skipping device %s", device)
                    else:
                        self._devices_cache.append(models.Device.model_validate(existing_device.model_dump()))
                await session.commit()
            self.logger.info("Cache refreshed")
        except Exception as e:
            self.logger.error("Failed to refresh cache: %s", e)

    async def skill_preparations(self) -> None:
        """Perform any additional skill preparations beyond constructor initialization."""
        pass

    async def calculate_certainty(self, intent_analysis_result: commons.IntentAnalysisResult) -> float:
        """Calculate skill certainty for handling the given intent.

        Simple keyword-based certainty calculation. Returns maximum certainty
        if 'spotify' is mentioned in the parsed nouns, otherwise no certainty.

        Args:
            intent_analysis_result: Parsed intent from voice command.

        Returns:
            1.0 if 'spotify' keyword found, 0.0 otherwise.
        """
        if "spotify" in intent_analysis_result.nouns:
            return 1.0
        return 0

    async def find_parameters(self, action: Action, intent_analysis_result: commons.IntentAnalysisResult) -> Parameters:
        """Extract command parameters from the intent analysis result.

        Parses numbers and their context from voice commands to extract
        playlist IDs, device IDs, and volume levels based on the action type.

        Args:
            action: The action being performed.
            intent_analysis_result: Parsed intent containing numbers and context.

        Returns:
            Parameters object with extracted values and cached data.
        """
        parameters = Parameters()
        parameters.playlists = self.playlists
        parameters.devices = self.devices

        if action == Action.PLAY_PLAYLIST:
            # AIDEV-NOTE: Extract playlist and device numbers based on context words
            for result in intent_analysis_result.numbers:
                if result.previous_token:
                    if "playlist" in result.previous_token:
                        parameters.playlist_id = result.number_token
                    if "device" in result.previous_token:
                        parameters.device_id = result.number_token

        elif action == Action.SET_VOLUME:
            # AIDEV-NOTE: Look for "to" keyword before volume number
            for result in intent_analysis_result.numbers:
                if result.previous_token and "to" in result.previous_token:
                    parameters.volume = result.number_token

        return parameters

    def get_playlist_id_by_index(self, index: int, playlists: list[dict[str, str]]) -> str | None:
        """Get Spotify playlist ID by 1-based index.

        Args:
            index: 1-based playlist index from voice command.
            playlists: List of playlist dictionaries from Spotify API.

        Returns:
            Spotify playlist ID string or None if index is invalid.
        """
        try:
            return playlists[index - 1]["id"]
        except IndexError:
            self.logger.error("Invalid playlist index.")
            return None

    def get_device_by_index(self, index: int, devices: list[models.Device]) -> models.Device | None:
        """Get device by 1-based index.

        Args:
            index: 1-based device index from voice command.
            devices: List of available devices.

        Returns:
            Device model or None if index is invalid.
        """
        try:
            return devices[index - 1]
        except IndexError:
            self.logger.error("Invalid device index.")
            return None

    async def get_main_device(self, room: str) -> models.Device | None:
        """Find the main device for a specific room.

        Args:
            room: Room name to search for.

        Returns:
            Main device for the room or None if not found.
        """
        for device in self.devices:
            if device.is_main and device.room == room:
                return device
        return None

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        """Generate response text using Jinja2 templates.

        Args:
            action: The action being performed.
            parameters: Command parameters for template context.

        Returns:
            Rendered response text for MQTT transmission.
        """
        return self.action_to_answer[action].render(
            action=action,
            parameters=parameters,
        )

    async def start_spotify_playlist(self, device_spotify: models.Device, playlist_id: str) -> None:
        """Start playlist playback on a specific device with optimal settings.

        Initiates playlist playback, waits for device activation, then applies
        the device's default volume and enables shuffle mode for better experience.

        Args:
            device_spotify: Target device for playback.
            playlist_id: Spotify playlist ID to play.

        Note:
            Includes a 3-second delay to allow device activation before
            applying volume and shuffle settings.
        """
        try:
            await asyncio.to_thread(
                self.sp.start_playback,
                device_id=device_spotify.spotify_id,
                context_uri=f"spotify:playlist:{playlist_id}",
            )
            # AIDEV-NOTE: Critical timing - device needs activation time before volume/shuffle
            await asyncio.sleep(3.0)
            await asyncio.to_thread(self.sp.volume, volume_percent=device_spotify.default_volume)
            await asyncio.to_thread(self.sp.shuffle, state=True)
            self.logger.info("Started playlist '%s' on device '%s'", playlist_id, device_spotify.name)
        except spotipy.SpotifyException as e:
            self.logger.error("Failed to start playlist '%s' on device '%s': %s", playlist_id, device_spotify.name, e)
        except Exception as e:
            self.logger.error(
                "Unexpected error while starting playlist '%s' on device '%s': %s",
                playlist_id,
                device_spotify.name,
                e,
                exc_info=True,
            )

    async def process_request(self, intent_analysis_result: commons.IntentAnalysisResult) -> None:
        """Process incoming voice command and execute corresponding Spotify action.

        Main entry point for command processing. Parses the command text to identify
        the action, extracts parameters, generates a response, and executes the action.

        Args:
            intent_analysis_result: Parsed voice command with intent analysis.

        Note:
            Sends immediate response via MQTT before executing the action to provide
            quick user feedback while Spotify API calls complete.
        """
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            self.logger.error("Unrecognized action in text: %s", intent_analysis_result.client_request.text)
            return

        parameters = await self.find_parameters(action, intent_analysis_result=intent_analysis_result)
        if parameters is None:
            self.logger.error("No parameters found for the action.")
            return

        # AIDEV-NOTE: Send response immediately for better UX while API calls execute
        answer = self.get_answer(action, parameters)
        self.add_task(self.send_response(answer, client_request=intent_analysis_result.client_request))

        try:
            await self._execute_action(action, parameters, intent_analysis_result)
        except spotipy.SpotifyException as e:
            self.logger.error("Spotify API error during '%s': %s", action.name, e)
        except Exception as e:
            self.logger.error("Unexpected error during '%s': %s", action.name, e, exc_info=True)

    async def _execute_action(
        self, action: Action, parameters: Parameters, intent_analysis_result: commons.IntentAnalysisResult
    ) -> None:
        """Execute the specific action based on the identified command.

        Dispatches to appropriate handler methods based on the action type.
        Actions that don't require Spotify API calls (like LIST commands) are
        handled purely through template responses.

        Args:
            action: The action to execute.
            parameters: Extracted command parameters.
            intent_analysis_result: Original intent analysis for context.
        """
        # AIDEV-NOTE: Only actions requiring API calls are handled here
        if action == Action.CONTINUE:
            await self._handle_continue_action(intent_analysis_result.client_request.room)
        elif action == Action.PLAY_PLAYLIST:
            await self._handle_play_playlist_action(parameters, intent_analysis_result.client_request.room)
        elif action == Action.SET_VOLUME:
            await self._handle_set_volume_action(parameters)
        elif action == Action.STOP_PLAYBACK:
            await self._handle_stop_playback_action()
        elif action == Action.NEXT_TRACK:
            await self._handle_next_track_action()

    async def _handle_continue_action(self, room: str) -> None:
        """Handle continue/resume playback command for a specific room.

        Intelligently manages playback continuation by either transferring
        existing playback to the room's main device or starting fresh playback.

        Args:
            room: Target room for playback continuation.

        Note:
            Checks current playback state and transfers if playing elsewhere,
            or starts new playback if stopped.
        """
        current_playback = await asyncio.to_thread(self.sp.current_playback)
        main_device = await self.get_main_device(room)

        if current_playback and current_playback["is_playing"]:
            current_device_id = current_playback["device"]["id"]
            if main_device and main_device.spotify_id != current_device_id:
                # AIDEV-NOTE: Transfer active playback to room's main device
                await asyncio.to_thread(self.sp.transfer_playback, device_id=main_device.spotify_id)
                self.logger.info("Transferred playback to device '%s' in room '%s'", main_device.name, room)
            else:
                self.logger.info("Playback is already on the correct device in room '%s'", room)
        elif main_device:
            # AIDEV-NOTE: Start playback if nothing is currently playing
            await asyncio.to_thread(self.sp.start_playback, device_id=main_device.spotify_id)
            self.logger.info("Started playback on device '%s' in room '%s'", main_device.name, room)
        else:
            self.logger.error("No main device found in room '%s'", room)

    async def _handle_play_playlist_action(self, parameters: Parameters, room: str) -> None:
        """Handle playlist playback command with device selection.

        Starts playlist playback on either a specified device or the room's main device.
        Validates playlist and device indices before initiating playback.

        Args:
            parameters: Command parameters with playlist/device IDs.
            room: Current room for fallback device selection.
        """
        if parameters.device_id:
            device_spotify = self.get_device_by_index(parameters.device_id, parameters.devices)
        else:
            # AIDEV-NOTE: Default to room's main device if no specific device requested
            device_spotify = await self.get_main_device(room)

        if parameters.playlist_id is not None and device_spotify:
            playlist_id = self.get_playlist_id_by_index(parameters.playlist_id, parameters.playlists)
            if playlist_id:
                await self.start_spotify_playlist(device_spotify=device_spotify, playlist_id=playlist_id)
            else:
                self.logger.error("Playlist ID '%s' not found in playlists.", parameters.playlist_id)
        else:
            self.logger.error("Device ID '%s' or main device not found.", parameters.device_id)

    async def _handle_set_volume_action(self, parameters: Parameters) -> None:
        """Handle volume adjustment command with safety limits.

        Args:
            parameters: Command parameters containing target volume.

        Note:
            Volume is capped at MAX_VOLUME_LIMIT for hearing protection.
        """
        if parameters.volume is not None:
            # AIDEV-NOTE: Critical safety limit - never exceed MAX_VOLUME_LIMIT
            final_volume = parameters.volume if parameters.volume < MAX_VOLUME_LIMIT else MAX_VOLUME_LIMIT
            await asyncio.to_thread(self.sp.volume, volume_percent=final_volume)
            self.logger.info("Spotify volume set to %d%%", final_volume)
        else:
            self.logger.error("No volume level provided in the request.")

    async def _handle_stop_playback_action(self) -> None:
        """Handle stop/pause playback command.

        Pauses current Spotify playback across all devices.
        """
        await asyncio.to_thread(self.sp.pause_playback)
        self.logger.info("Playback paused.")

    async def _handle_next_track_action(self) -> None:
        """Handle next track/skip command.

        Advances to the next track in the current playback context.
        """
        await asyncio.to_thread(self.sp.next_track)
        self.logger.info("Skipped to next track.")
