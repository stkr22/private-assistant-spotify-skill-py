import unittest
from unittest.mock import Mock, patch

import jinja2
import spotipy
from private_assistant_commons import messages
from private_assistant_spotify_skill import models
from private_assistant_spotify_skill.spotify_skill import Action, Parameters, SpotifySkill


class TestSpotifySkill(unittest.TestCase):
    def setUp(self):
        self.mock_mqtt_client = Mock()
        self.mock_config = Mock()
        self.mock_sp_oauth = Mock()
        self.mock_spotify = Mock(spec=spotipy.Spotify)
        self.mock_template_env = jinja2.Environment(
            loader=jinja2.PackageLoader(
                "private_assistant_spotify_skill",
                "templates",
            )
        )

        with patch("spotipy.Spotify", return_value=self.mock_spotify):
            self.skill = SpotifySkill(
                config_obj=self.mock_config,
                mqtt_client=self.mock_mqtt_client,
                template_env=self.mock_template_env,
                sp_oauth=self.mock_sp_oauth,
                db_engine=Mock(),
            )

    def test_find_parameters_for_set_volume(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.numbers = [Mock(number_token=60, previous_token="to")]

        # Mock the database session to return an empty list for devices
        with patch("private_assistant_spotify_skill.spotify_skill.Session") as mock_session:
            mock_session_instance = mock_session.return_value.__enter__.return_value
            mock_session_instance.exec.return_value.all.return_value = []

            # Call the method under test
            parameters = self.skill.find_parameters(Action.SET_VOLUME, mock_intent_result)

            # Check that the volume is correctly extracted
            self.assertEqual(parameters.volume, 60)
            # Ensure other parameters are set to default (empty lists)
            self.assertEqual(parameters.devices, [])

    def test_process_request_set_volume(self):
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

        with patch("private_assistant_spotify_skill.spotify_skill.Session") as mock_session:
            mock_session_instance = mock_session.return_value.__enter__.return_value
            mock_session_instance.exec.return_value.all.return_value = []

            with patch.object(self.skill, "get_answer") as mock_get_answer:
                mock_get_answer.return_value = "Volume set to 60%"

                # Call the process_request method
                self.skill.process_request(mock_intent_result)

                # Verify that the volume API was called with the correct volume
                self.mock_spotify.volume.assert_called_once_with(volume_percent=60)
                # Verify that the response was generated and sent
                mock_get_answer.assert_called_once_with(
                    Action.SET_VOLUME, Parameters(playlist_id=None, device_id=None, playlists=[], devices=[], volume=60)
                )

    def test_process_request_set_volume_no_volume_provided(self):
        # Mock the intent analysis result without any numbers
        mock_client_request = Mock()
        mock_client_request.text = "Please set spotify volume"

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.numbers = []

        # Mock the database session to return an empty list for devices
        with patch("private_assistant_spotify_skill.spotify_skill.Session") as mock_session:
            mock_session_instance = mock_session.return_value.__enter__.return_value
            mock_session_instance.exec.return_value.all.return_value = []

            with patch.object(self.skill, "get_answer") as mock_get_answer:
                # Call the process_request method
                self.skill.process_request(mock_intent_result)

                # Verify that the volume API was not called
                self.mock_spotify.volume.assert_not_called()
                # Verify that the response indicates no volume was set
                mock_get_answer.assert_called_once_with(
                    Action.SET_VOLUME,
                    Parameters(playlist_id=None, device_id=None, playlists=[], devices=[], volume=None),
                )

    def test_play_playlist_action_with_device(self):
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
        with patch.object(self.skill, "find_parameters", return_value=parameters):
            with patch.object(self.skill, "get_device_by_index", return_value=device):
                with patch.object(self.skill, "start_spotify_playlist") as mock_start_playlist:
                    # Call the process_request method
                    self.skill.process_request(mock_intent_result)

                    # Verify that the playlist was started
                    mock_start_playlist.assert_called_once_with(device_spotify=device, playlist_id="XX")

                    # Verify the output
                    answer = self.skill.get_answer(Action.PLAY_PLAYLIST, parameters)
                    self.assertEqual(answer.strip(), "Started playing playlist Chill Vibes on device 1.")

    def test_play_playlist_action_with_main_device(self):
        # Mock the IntentAnalysisResult and its client_request attribute
        mock_intent_result = Mock()
        mock_intent_result.client_request = Mock()
        mock_intent_result.client_request.room = "living_room"
        mock_intent_result.client_request.text = "please play spotify playlist 2"

        # Mock parameters with playlist information but no device_id
        device = Mock(spec=models.Device)
        device.id = 1
        device.name = "living_room_speaker"
        parameters = Parameters(
            playlist_id="0",
            device_id=None,
            playlists=[{"id": "XX", "name": "Chill Vibes"}, {"id": "XXX", "name": "Workout Hits"}],
            devices=[device],
        )
        with patch.object(self.skill, "find_parameters", return_value=parameters):
            with patch.object(self.skill, "get_main_device", return_value=device):
                with patch.object(self.skill, "start_spotify_playlist") as mock_start_playlist:
                    # Call the process_request method
                    self.skill.process_request(mock_intent_result)

                    # Verify that the playlist was started
                    mock_start_playlist.assert_called_once_with(
                        device_spotify=device,
                        playlist_id="XXX",
                    )

                    # Verify the output
                    answer = self.skill.get_answer(Action.PLAY_PLAYLIST, parameters)
                    self.assertEqual(answer.strip(), "Started playing playlist Workout Hits on the main device.")
