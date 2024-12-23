import asyncio
import enum
import logging
import string

import aiohttp
import aiomqtt
import jinja2
import private_assistant_commons as commons
import pyamaha
import spotipy
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from private_assistant_spotify_skill import config, models


class Parameters(BaseModel):
    playlist_id: int | None = None
    device_id: int | None = None
    playlists: list[dict[str, str]] = []
    devices: list[models.Device] = []
    volume: int | None = None  # Attribute for volume level


class Action(enum.Enum):
    HELP = ["help"]
    LIST_PLAYLISTS = ["list", "playlists"]
    LIST_DEVICES = ["list", "devices"]
    PLAY_PLAYLIST = ["play", "playlist"]
    STOP_PLAYBACK = ["stop", "playback"]
    NEXT_TRACK = ["next", "track"]
    SET_VOLUME = ["set", "volume"]
    CONTINUE = ["continue"]

    @classmethod
    def find_matching_action(cls, text: str):
        text = text.translate(str.maketrans("", "", string.punctuation))
        text_words = set(text.lower().split())

        for action in cls:
            if all(word in text_words for word in action.value):
                return action
        return None


class SpotifySkill(commons.BaseSkill):
    CACHE_REFRESH_INTERVAL = 3600  # 1 hour in seconds

    def __init__(
        self,
        config_obj: config.SkillConfig,
        mqtt_client: aiomqtt.Client,
        template_env: jinja2.Environment,
        sp_oauth: spotipy.SpotifyOAuth,
        db_engine: AsyncEngine,
        task_group: asyncio.TaskGroup,
        logger: logging.Logger,
    ) -> None:
        super().__init__(config_obj, mqtt_client, task_group, logger=logger)
        self.sp = spotipy.Spotify(auth_manager=sp_oauth)
        self.db_engine = db_engine
        self.task_group = task_group

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

        self._playlists_cache: list[dict[str, str]] = []
        self._devices_cache: list[models.Device] = []
        self.add_task(self._refresh_cache())
        self._refresh_cache_loop_task = self.add_task(self._refresh_cache_loop())

    @property
    def playlists(self) -> list[dict[str, str]]:
        return self._playlists_cache

    @property
    def devices(self) -> list[models.Device]:
        return self._devices_cache

    async def _refresh_cache_loop(self):
        while True:
            await self._refresh_cache()
            await asyncio.sleep(self.CACHE_REFRESH_INTERVAL)

    async def _refresh_cache(self):
        try:
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

    async def calculate_certainty(self, intent_analysis_result: commons.IntentAnalysisResult) -> float:
        if "spotify" in intent_analysis_result.nouns:
            return 1.0
        return 0

    async def find_parameters(self, action: Action, intent_analysis_result: commons.IntentAnalysisResult) -> Parameters:
        parameters = Parameters()
        parameters.playlists = self.playlists
        parameters.devices = self.devices

        if action == Action.PLAY_PLAYLIST:
            for result in intent_analysis_result.numbers:
                if result.previous_token:
                    if "playlist" in result.previous_token:
                        parameters.playlist_id = result.number_token
                    if "device" in result.previous_token:
                        parameters.device_id = result.number_token

        elif action == Action.SET_VOLUME:
            for result in intent_analysis_result.numbers:
                if result.previous_token and "to" in result.previous_token:
                    parameters.volume = result.number_token

        return parameters

    def get_playlist_id_by_index(self, index: int, playlists: list[dict[str, str]]) -> str | None:
        try:
            return playlists[index - 1]["id"]
        except IndexError:
            self.logger.error("Invalid playlist index.")
            return None

    def get_device_by_index(self, index: int, devices: list[models.Device]) -> models.Device | None:
        try:
            return devices[index - 1]
        except IndexError:
            self.logger.error("Invalid device index.")
            return None

    async def get_main_device(self, room: str) -> models.Device | None:
        for device in self.devices:
            if device.is_main and device.room == room:
                return device
        return None

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        return self.action_to_answer[action].render(
            action=action,
            parameters=parameters,
        )

    async def start_spotify_playlist(self, device_spotify: models.Device, playlist_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.sp.start_playback,
                device_id=device_spotify.spotify_id,
                context_uri=f"spotify:playlist:{playlist_id}",
            )
            # waiting period for device to turn on
            await asyncio.sleep(3.0)
            await asyncio.to_thread(self.sp.volume, volume_percent=device_spotify.default_volume)
            if device_spotify.ip:
                async with aiohttp.ClientSession() as client:
                    await pyamaha.AsyncDevice(client, device_spotify.ip).get(
                        pyamaha.Zone.set_sound_program("main", program="music")
                    )
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
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            self.logger.error("Unrecognized action in text: %s", intent_analysis_result.client_request.text)
            return

        parameters = await self.find_parameters(action, intent_analysis_result=intent_analysis_result)
        if parameters is not None:
            answer = self.get_answer(action, parameters)
            self.add_task(self.send_response(answer, client_request=intent_analysis_result.client_request))

            try:
                if action == Action.CONTINUE:
                    current_playback = await asyncio.to_thread(self.sp.current_playback)
                    room = intent_analysis_result.client_request.room
                    main_device = await self.get_main_device(room)

                    if current_playback and current_playback["is_playing"]:
                        current_device_id = current_playback["device"]["id"]
                        if main_device and main_device.spotify_id != current_device_id:
                            await asyncio.to_thread(self.sp.transfer_playback, device_id=main_device.spotify_id)
                            self.logger.info("Transferred playback to device '%s' in room '%s'", main_device.name, room)
                        else:
                            self.logger.info("Playback is already on the correct device in room '%s'", room)
                    else:
                        if main_device:
                            await asyncio.to_thread(self.sp.start_playback, device_id=main_device.spotify_id)
                            self.logger.info("Started playback on device '%s' in room '%s'", main_device.name, room)
                        else:
                            self.logger.error("No main device found in room '%s'", room)

                elif action == Action.PLAY_PLAYLIST:
                    if parameters.device_id:
                        device_spotify = self.get_device_by_index(parameters.device_id, parameters.devices)
                    else:
                        device_spotify = await self.get_main_device(intent_analysis_result.client_request.room)
                    if parameters.playlist_id is not None and device_spotify:
                        playlist_id = self.get_playlist_id_by_index(parameters.playlist_id, parameters.playlists)
                        if playlist_id:
                            await self.start_spotify_playlist(device_spotify=device_spotify, playlist_id=playlist_id)
                        else:
                            self.logger.error("Playlist ID '%s' not found in playlists.", parameters.playlist_id)
                    else:
                        self.logger.error("Device ID '%s' or main device not found.", parameters.device_id)

                elif action == Action.SET_VOLUME:
                    if parameters.volume is not None:
                        final_volume = parameters.volume if parameters.volume < 90 else 90
                        await asyncio.to_thread(self.sp.volume, volume_percent=final_volume)
                        self.logger.info("Spotify volume set to %d%%", final_volume)
                    else:
                        self.logger.error("No volume level provided in the request.")

                elif action == Action.STOP_PLAYBACK:
                    await asyncio.to_thread(self.sp.pause_playback)
                    self.logger.info("Playback paused.")
                elif action == Action.NEXT_TRACK:
                    await asyncio.to_thread(self.sp.next_track)
                    self.logger.info("Skipped to next track.")
            except spotipy.SpotifyException as e:
                self.logger.error("Spotify API error during '%s': %s", action.name, e)
            except Exception as e:
                self.logger.error("Unexpected error during '%s': %s", action.name, e, exc_info=True)
        else:
            self.logger.error("No parameters found for the action.")
