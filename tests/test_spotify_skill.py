import unittest
from unittest.mock import AsyncMock, Mock, patch

import jinja2
import spotipy
from private_assistant_commons import messages

from private_assistant_spotify_skill import models
from private_assistant_spotify_skill.spotify_skill import Action, Parameters, SpotifySkill


class TestSpotifySkill(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_mqtt_client = Mock()
        self.mock_config = Mock()
        self.mock_sp_oauth = Mock()
        self.mock_spotify = AsyncMock(spec=spotipy.Spotify)
        self.mock_template_env = jinja2.Environment(
            loader=jinja2.PackageLoader(
                "private_assistant_spotify_skill",
                "templates",
            )
        )

        self.mock_task_group = AsyncMock()
        self.mock_logger = Mock()

        # Patch spotipy.Spotify with a mock
        with patch("spotipy.Spotify", return_value=self.mock_spotify):
            self.skill = SpotifySkill(
                config_obj=self.mock_config,
                mqtt_client=self.mock_mqtt_client,
                template_env=self.mock_template_env,
                sp_oauth=self.mock_sp_oauth,
                db_engine=Mock(),
                task_group=self.mock_task_group,
                logger=self.mock_logger,
            )

    async def test_find_parameters_for_set_volume(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.numbers = [Mock(number_token=60, previous_token="to")]

        # Mock the database session to return an empty list for devices
        with patch("private_assistant_spotify_skill.spotify_skill.AsyncSession") as mock_session:
            mock_session_instance = mock_session.return_value.__aenter__.return_value
            mock_session_instance.execute.return_value.scalars.return_value.all.return_value = []

            # Call the method under test
            parameters = await self.skill.find_parameters(Action.SET_VOLUME, mock_intent_result)

            # Check that the volume is correctly extracted
            self.assertEqual(parameters.volume, 60)
            # Ensure other parameters are set to default (empty lists)
            self.assertEqual(parameters.devices, [])

    async def test_process_request_set_volume(self):
        # Mock the intent analysis result
        mock_client_request = Mock()
        mock_client_request.text = "Please set spotify volume to 60"

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.numbers = [Mock(number_token=60, previous_token="to")]

        # Set up mock template return value
        mock_template = Mock()
        mock_template.render.return_value = "Volume set to 60%"
        self.skill.action_to_answer[Action.SET_VOLUME] = mock_template

        with patch("private_assistant_spotify_skill.spotify_skill.AsyncSession") as mock_session:
            mock_session_instance = mock_session.return_value.__aenter__.return_value
            mock_session_instance.execute.return_value.scalars.return_value.all.return_value = []

            with patch("asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = None
                await self.skill.process_request(mock_intent_result)

                # Verify that the volume API was called with the correct volume
                mock_to_thread.assert_called_with(self.mock_spotify.volume, volume_percent=60)

    async def test_play_playlist_action_with_device(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "living_room"
        mock_intent_result.client_request.text = "please play spotify playlist 1"

        device = Mock(spec=models.Device)
        device.id = 1
        device.name = "living_room_speaker"
        # Mock parameters with playlist and device information
        parameters = Parameters(
            playlist_id="1",
            device_id=1,  # Using an integer to represent the device index
            playlists=[{"id": "XX", "name": "Chill Vibes"}, {"id": "XXX", "name": "Workout Hits"}],
            devices=[device],
        )
        with (
            patch.object(self.skill, "find_parameters", return_value=parameters),
            patch.object(self.skill, "get_device_by_index", return_value=device),
            patch("asyncio.to_thread") as mock_to_thread,
        ):
            await self.skill.process_request(mock_intent_result)
            # Verify that shuffle was called last (after volume call was removed pyamaha code)
            mock_to_thread.assert_called_with(self.mock_spotify.shuffle, state=True)

    async def test_continue_action_music_playing_on_correct_device(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "living_room"
        mock_intent_result.client_request.text = "continue spotify"

        # Mock the current playback to simulate music playing on the correct device
        self.mock_spotify.current_playback.return_value = {
            "is_playing": True,
            "device": {"id": "device_id_living_room"},
        }

        # Mock the parameters
        parameters = Parameters(
            playlist_id=None,
            device_id=None,
            playlists=[],
            devices=[
                models.Device(
                    spotify_id="device_id_living_room", name="Living Room Speaker", room="living_room", is_main=True
                )
            ],
        )

        with (
            patch.object(self.skill, "find_parameters", return_value=parameters),
            patch.object(self.skill, "get_main_device", return_value=parameters.devices[0]),
        ):
            await self.skill.process_request(mock_intent_result)

            # Verify that transfer_playback was not called since it's already on the correct device
            self.mock_spotify.transfer_playback.assert_not_called()

    async def test_continue_action_transfer_playback(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "kitchen"
        mock_intent_result.client_request.text = "continue spotify"

        # Mock the current playback to simulate music playing on a different device
        self.mock_spotify.current_playback.return_value = {
            "is_playing": True,
            "device": {"id": "device_id_living_room"},
        }

        # Mock the parameters
        parameters = Parameters(
            playlist_id=None,
            device_id=None,
            playlists=[],
            devices=[
                models.Device(spotify_id="device_id_kitchen", name="Kitchen Speaker", room="kitchen", is_main=True)
            ],
        )

        with (
            patch.object(self.skill, "find_parameters", return_value=parameters),
            patch.object(self.skill, "get_main_device", return_value=parameters.devices[0]),
            patch("asyncio.to_thread") as mock_to_thread,
        ):
            await self.skill.process_request(mock_intent_result)

            # Verify that transfer_playback was called to the kitchen device
            mock_to_thread.assert_called_with(self.mock_spotify.transfer_playback, device_id="device_id_kitchen")

    async def test_continue_action_start_playback(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "bedroom"
        mock_intent_result.client_request.text = "continue spotify"

        # Mock the current playback to simulate no music playing
        self.mock_spotify.current_playback.return_value = {"is_playing": False}

        # Mock the parameters
        parameters = Parameters(
            playlist_id=None,
            device_id=None,
            playlists=[],
            devices=[
                models.Device(spotify_id="device_id_bedroom", name="Bedroom Speaker", room="bedroom", is_main=True)
            ],
        )

        with (
            patch.object(self.skill, "find_parameters", return_value=parameters),
            patch.object(self.skill, "get_main_device", return_value=parameters.devices[0]),
            patch("asyncio.to_thread") as mock_to_thread,
        ):
            await self.skill.process_request(mock_intent_result)

            # Verify that start_playback was called on the main device in the bedroom
            mock_to_thread.assert_called_with(self.mock_spotify.transfer_playback, device_id="device_id_bedroom")

    async def test_continue_action_no_main_device_found(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "garage"
        mock_intent_result.client_request.text = "continue spotify"

        # Mock the current playback to simulate no music playing
        self.mock_spotify.current_playback.return_value = {"is_playing": False}

        # Mock the parameters
        parameters = Parameters(playlist_id=None, device_id=None, playlists=[], devices=[])

        with (
            patch.object(self.skill, "find_parameters", return_value=parameters),
            patch.object(self.skill, "get_main_device", return_value=None),
        ):
            await self.skill.process_request(mock_intent_result)

            # Verify that start_playback was not called because no main device was found
            self.mock_spotify.start_playback.assert_not_called()
