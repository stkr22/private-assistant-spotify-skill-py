import enum
import string
import threading

import jinja2
import paho.mqtt.client as mqtt
import private_assistant_commons as commons
import pyamaha
import spotipy
import sqlalchemy
from private_assistant_commons import messages
from private_assistant_commons.skill_logger import SkillLogger
from pydantic import BaseModel
from sqlmodel import Session, select

from private_assistant_spotify_skill import models

logger = SkillLogger.get_logger(__name__)


class Parameters(BaseModel):
    playlist_id: int | None = None
    device_id: int | None = None
    playlists: list[dict[str, str]] = []
    devices: list[models.Device] = []
    volume: int | None = None  # New attribute for volume level


class Action(enum.Enum):
    HELP = ["help"]
    LIST_PLAYLISTS = ["list", "playlists"]
    LIST_DEVICES = ["list", "devices"]
    PLAY_PLAYLIST = ["play", "playlist"]
    STOP_PLAYBACK = ["stop", "playback"]
    NEXT_TRACK = ["next", "track"]
    SET_VOLUME = ["set", "volume"]

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
        config_obj: commons.SkillConfig,
        mqtt_client: mqtt.Client,
        template_env: jinja2.Environment,
        sp_oauth: spotipy.SpotifyOAuth,
        db_engine: sqlalchemy.Engine,
    ) -> None:
        super().__init__(config_obj, mqtt_client)
        self.sp = spotipy.Spotify(auth_manager=sp_oauth)
        self.db_engine = db_engine

        self.action_to_answer: dict[Action, jinja2.Template] = {
            Action.HELP: template_env.get_template("help.j2"),
            Action.LIST_PLAYLISTS: template_env.get_template("list_playlists.j2"),
            Action.LIST_DEVICES: template_env.get_template("list_devices.j2"),
            Action.PLAY_PLAYLIST: template_env.get_template("playback_started.j2"),
            Action.STOP_PLAYBACK: template_env.get_template("playback_stopped.j2"),
            Action.NEXT_TRACK: template_env.get_template("next_track.j2"),
        }
        self.template_env = template_env

        self._playlists_cache: list[dict[str, str]] = []
        self._refresh_cache()
        self._schedule_cache_refresh()

    @property
    def playlists(self) -> list[dict[str, str]]:
        return self._playlists_cache

    @property
    def devices(self) -> list[models.Device]:
        with Session(self.db_engine) as session:
            return list(session.exec(select(models.Device)).all())

    def _refresh_cache(self):
        try:
            self._playlists_cache = sorted(self.sp.current_user_playlists()["items"], key=lambda x: x["id"])
            spotify_devices = sorted(self.sp.devices()["devices"], key=lambda x: x["id"])
            with Session(self.db_engine) as session:
                for device in spotify_devices:
                    existing_device = session.exec(
                        select(models.Device).where(models.Device.spotify_id == device["id"])
                    ).first()
                    if not existing_device:
                        try:
                            room, name = device["name"].split("-", 1)
                            new_device = models.Device(spotify_id=device["id"], name=name, room=room.replace("_", ""))
                            session.add(new_device)
                        except ValueError:
                            logger.error("Device name is broken, skipping device %s", device)
                session.commit()
            logger.info("Cache refreshed")
        except Exception as e:
            logger.error("Failed to refresh cache: %s", e)

    def _schedule_cache_refresh(self):
        self._cache_refresh_timer = threading.Timer(self.CACHE_REFRESH_INTERVAL, self._refresh_cache_and_reschedule)
        self._cache_refresh_timer.daemon = True
        self._cache_refresh_timer.start()

    def _refresh_cache_and_reschedule(self):
        self._refresh_cache()
        self._schedule_cache_refresh()

    def calculate_certainty(self, intent_analysis_result: messages.IntentAnalysisResult) -> float:
        if "spotify" in intent_analysis_result.nouns:
            return 1.0
        return 0

    def find_parameters(self, action: Action, intent_analysis_result: messages.IntentAnalysisResult) -> Parameters:
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

    def get_device_id_by_index(self, index: int, devices: list[models.Device]) -> models.Device | None:
        try:
            return devices[index - 1]
        except IndexError:
            logger.error("Invalid device index.")
            return None

    def get_playlist_id_by_index(self, index: int, playlists: list[dict[str, str]]) -> str | None:
        try:
            return playlists[index - 1]["id"]
        except IndexError:
            logger.error("Invalid playlist index.")
            return None

    def get_main_device_id(self, room: str) -> models.Device | None:
        with Session(self.db_engine) as session:
            main_device = session.exec(
                select(models.Device).where(models.Device.room == room, models.Device.is_main.__eq__(True))
            ).first()
            if main_device:
                return main_device
        return None

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        answer = self.action_to_answer[action].render(
            action=action,
            parameters=parameters,
        )
        return answer

    def start_spotify_playlist(self, device_spotify: models.Device, playlist_id: str) -> None:
        try:
            self.sp.start_playback(device_id=device_spotify.spotify_id, context_uri=f"spotify:playlist:{playlist_id}")
            self.sp.volume(volume_percent=55, device_id=device_spotify.spotify_id)
            if device_spotify.ip:
                pyamaha.Device(device_spotify.ip).get(pyamaha.Zone.set_sound_program("main", program="music"))
            self.sp.shuffle(state=True, device_id=device_spotify.spotify_id)
            logger.info("Started playlist '%s' on device '%s'", playlist_id, device_spotify.name)
        except spotipy.SpotifyException as e:
            logger.error("Failed to start playlist '%s' on device '%s': %s", playlist_id, device_spotify.name, e)
        except Exception as e:
            logger.error(
                "Unexpected error while starting playlist '%s' on device '%s': %s", playlist_id, device_spotify.name, e
            )

    def process_request(self, intent_analysis_result: messages.IntentAnalysisResult) -> None:
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            logger.error("Unrecognized action in text: %s", intent_analysis_result.client_request.text)
            return

        parameters = self.find_parameters(action, intent_analysis_result=intent_analysis_result)
        if parameters is not None:
            answer = self.get_answer(action, parameters)
            self.add_text_to_output_topic(answer, client_request=intent_analysis_result.client_request)

            try:
                if action == Action.PLAY_PLAYLIST:
                    if parameters.device_id:
                        device_spotify = self.get_device_id_by_index(parameters.device_id, parameters.devices)
                    else:
                        device_spotify = self.get_main_device_id(intent_analysis_result.client_request.room)
                    if parameters.playlist_id and device_spotify:
                        playlist_id = self.get_playlist_id_by_index(parameters.playlist_id, parameters.playlists)
                        if playlist_id:
                            self.start_spotify_playlist(device_spotify=device_spotify, playlist_id=playlist_id)
                        else:
                            logger.error("Playlist ID '%s' not found in playlists.", parameters.playlist_id)
                    else:
                        logger.error("Device ID '%s' or main device not found.", parameters.device_id)

                elif action == Action.SET_VOLUME:
                    if parameters.volume is not None:
                        final_volume = parameters.volume if parameters.volume < 90 else 90
                        self.sp.volume(volume_percent=final_volume)
                        logger.info("Spotify volume set to %d%%", final_volume)
                    else:
                        logger.error("No volume level provided in the request.")

                elif action == Action.STOP_PLAYBACK:
                    self.sp.pause_playback()
                    logger.info("Playback paused.")
                elif action == Action.NEXT_TRACK:
                    self.sp.next_track()
                    logger.info("Skipped to next track.")
            except spotipy.SpotifyException as e:
                logger.error("Spotify API error during '%s': %s", action.name, e)
            except Exception as e:
                logger.error("Unexpected error during '%s': %s", action.name, e)
        else:
            logger.error("No parameters found for the action.")
