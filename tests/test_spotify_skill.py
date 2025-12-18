"""Tests for the Spotify skill with intent-based architecture."""

import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

import jinja2
import spotipy
from private_assistant_commons import ClassifiedIntent, ClientRequest, Entity, IntentRequest, IntentType
from private_assistant_commons.database import GlobalDevice

from private_assistant_spotify_skill import models
from private_assistant_spotify_skill.spotify_skill import Parameters, SpotifySkill, SpotifySkillDependencies


def create_mock_intent_request(
    intent_type: IntentType,
    room: str = "living_room",
    entities: dict | None = None,
    raw_text: str = "",
    confidence: float = 0.9,
) -> IntentRequest:
    """Helper to create mock IntentRequest objects for testing."""
    if entities is None:
        entities = {}

    # Convert entity dicts to Entity objects
    processed_entities: dict[str, list[Entity]] = {}
    for key, values in entities.items():
        processed_entities[key] = [
            Entity(
                id=uuid.uuid4(),
                type=key,
                raw_text=str(v),
                normalized_value=str(v),
                confidence=0.9,
                metadata={},
            )
            for i, v in enumerate(values)
        ]

    mock_classified_intent = Mock(spec=ClassifiedIntent)
    mock_classified_intent.intent_type = intent_type
    mock_classified_intent.confidence = confidence
    mock_classified_intent.entities = processed_entities
    mock_classified_intent.raw_text = raw_text

    mock_client_request = Mock(spec=ClientRequest)
    mock_client_request.room = room
    mock_client_request.text = raw_text

    mock_intent_request = Mock(spec=IntentRequest)
    mock_intent_request.classified_intent = mock_classified_intent
    mock_intent_request.client_request = mock_client_request

    return mock_intent_request


def create_mock_spotify_device(
    name: str = "Speaker",
    room: str = "living_room",
    spotify_id: str = "spotify_device_123",
    is_main: bool = False,
    default_volume: int = 55,
) -> models.SpotifyDevice:
    """Helper to create mock SpotifyDevice objects."""
    mock_global_device = Mock(spec=GlobalDevice)
    mock_global_device.name = name
    mock_global_device.room = Mock()
    mock_global_device.room.name = room
    mock_global_device.device_attributes = {
        "spotify_id": spotify_id,
        "is_main": is_main,
        "default_volume": default_volume,
    }
    mock_global_device.device_type = Mock()
    mock_global_device.device_type.name = "spotify_device"

    return models.SpotifyDevice(
        global_device=mock_global_device,
        spotify_id=spotify_id,
        name=name,
        room=room,
        is_main=is_main,
        default_volume=default_volume,
    )


class TestSpotifySkill(unittest.IsolatedAsyncioTestCase):
    """Test cases for SpotifySkill with intent-based architecture."""

    async def asyncSetUp(self) -> None:
        """Set up test fixtures."""
        self.mock_mqtt_client = Mock()
        self.mock_config = Mock()
        # AIDEV-NOTE: BaseSkill uses client_id for SkillContext/MetricsCollector (Pydantic models)
        self.mock_config.client_id = "test_spotify_skill"
        self.mock_sp_oauth = Mock()
        self.mock_spotify = Mock(spec=spotipy.Spotify)
        self.mock_db_engine = Mock()
        self.mock_template_env = jinja2.Environment(
            loader=jinja2.PackageLoader(
                "private_assistant_spotify_skill",
                "templates",
            )
        )

        # Create a mock task that has add_done_callback method
        self.mock_task = Mock()
        self.mock_task.add_done_callback = Mock()

        self.mock_task_group = Mock()
        self.mock_task_group.create_task = Mock(return_value=self.mock_task)
        self.mock_logger = Mock()

        # Create dependencies container
        dependencies = SpotifySkillDependencies(
            db_engine=self.mock_db_engine,
            template_env=self.mock_template_env,
            sp_oauth=self.mock_sp_oauth,
        )

        # Patch spotipy.Spotify with a mock
        with patch("spotipy.Spotify", return_value=self.mock_spotify):
            self.skill = SpotifySkill(
                config_obj=self.mock_config,
                mqtt_client=self.mock_mqtt_client,
                dependencies=dependencies,
                task_group=self.mock_task_group,
                logger=self.mock_logger,
            )

        # Set up mock devices in global_devices
        self.mock_devices = [
            create_mock_spotify_device(
                name="Living Room Speaker",
                room="living_room",
                spotify_id="device_living_room",
                is_main=True,
            ),
            create_mock_spotify_device(
                name="Kitchen Speaker",
                room="kitchen",
                spotify_id="device_kitchen",
                is_main=True,
            ),
        ]

    async def test_process_request_volume_set(self) -> None:
        """Test MEDIA_VOLUME_SET intent processing."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.MEDIA_VOLUME_SET,
            room="living_room",
            entities={"number": [60]},
            raw_text="set spotify volume to 60",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
        ):
            await self.skill.process_request(intent_request)

            # Verify volume was set to 60
            mock_to_thread.assert_called_with(self.mock_spotify.volume, volume_percent=60)

    async def test_process_request_volume_set_with_max_limit(self) -> None:
        """Test MEDIA_VOLUME_SET intent respects MAX_VOLUME_LIMIT."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.MEDIA_VOLUME_SET,
            room="living_room",
            entities={"number": [100]},
            raw_text="set spotify volume to 100",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
        ):
            await self.skill.process_request(intent_request)

            # Verify volume was capped at MAX_VOLUME_LIMIT (90)
            mock_to_thread.assert_called_with(self.mock_spotify.volume, volume_percent=90)

    async def test_process_request_media_stop(self) -> None:
        """Test MEDIA_STOP intent processing."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.MEDIA_STOP,
            room="living_room",
            raw_text="stop spotify",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
        ):
            await self.skill.process_request(intent_request)

            # Verify pause_playback was called
            mock_to_thread.assert_called_with(self.mock_spotify.pause_playback)

    async def test_process_request_media_next(self) -> None:
        """Test MEDIA_NEXT intent processing."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.MEDIA_NEXT,
            room="living_room",
            raw_text="next track spotify",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock),
            patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
        ):
            await self.skill.process_request(intent_request)

            # Verify next_track was called
            mock_to_thread.assert_called_with(self.mock_spotify.next_track)

    async def test_process_request_query_list_playlists(self) -> None:
        """Test QUERY_LIST intent for playlists."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.QUERY_LIST,
            room="living_room",
            raw_text="list spotify playlists",
        )

        # Set up playlists cache
        self.skill._playlists_cache = [
            {"id": "playlist1", "name": "Chill Vibes"},
            {"id": "playlist2", "name": "Workout Hits"},
        ]

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock) as mock_send_response,
        ):
            await self.skill.process_request(intent_request)

            # Verify send_response was called
            mock_send_response.assert_called_once()
            # Check that response contains playlist info
            call_args = mock_send_response.call_args
            response_text = call_args[0][0]
            self.assertIn("playlist", response_text.lower())

    async def test_process_request_query_list_devices(self) -> None:
        """Test QUERY_LIST intent for devices."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.QUERY_LIST,
            room="living_room",
            entities={"device": ["speaker"]},
            raw_text="list spotify devices",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock) as mock_send_response,
        ):
            await self.skill.process_request(intent_request)

            # Verify send_response was called
            mock_send_response.assert_called_once()
            # Check that response contains device info
            call_args = mock_send_response.call_args
            response_text = call_args[0][0]
            self.assertIn("device", response_text.lower())

    async def test_process_request_system_help(self) -> None:
        """Test SYSTEM_HELP intent processing."""
        intent_request = create_mock_intent_request(
            intent_type=IntentType.SYSTEM_HELP,
            room="living_room",
            raw_text="spotify help",
        )

        with (
            patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices),
            patch.object(self.skill, "send_response", new_callable=AsyncMock) as mock_send_response,
        ):
            await self.skill.process_request(intent_request)

            # Verify send_response was called with help info
            mock_send_response.assert_called_once()

    async def test_get_main_device_found(self) -> None:
        """Test _get_main_device returns correct device."""
        with patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices):
            device = self.skill._get_main_device("living_room")

            self.assertIsNotNone(device)
            assert device is not None  # Type narrowing for mypy
            self.assertEqual(device.room, "living_room")
            self.assertTrue(device.is_main)

    async def test_get_main_device_not_found(self) -> None:
        """Test _get_main_device returns None for unknown room."""
        with patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices):
            device = self.skill._get_main_device("unknown_room")

            self.assertIsNone(device)

    async def test_get_device_by_index_valid(self) -> None:
        """Test _get_device_by_index with valid index."""
        with patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices):
            device = self.skill._get_device_by_index(1)

            self.assertIsNotNone(device)
            assert device is not None  # Type narrowing for mypy
            self.assertEqual(device.name, "Living Room Speaker")

    async def test_get_device_by_index_invalid(self) -> None:
        """Test _get_device_by_index with invalid index."""
        with patch.object(self.skill, "_get_spotify_devices", return_value=self.mock_devices):
            device = self.skill._get_device_by_index(999)

            self.assertIsNone(device)

    async def test_get_playlist_id_by_index_valid(self) -> None:
        """Test _get_playlist_id_by_index with valid index."""
        self.skill._playlists_cache = [
            {"id": "playlist1", "name": "Chill Vibes"},
            {"id": "playlist2", "name": "Workout Hits"},
        ]

        playlist_id = self.skill._get_playlist_id_by_index(1)
        self.assertEqual(playlist_id, "playlist1")

    async def test_get_playlist_id_by_index_invalid(self) -> None:
        """Test _get_playlist_id_by_index with invalid index."""
        self.skill._playlists_cache = [
            {"id": "playlist1", "name": "Chill Vibes"},
        ]

        playlist_id = self.skill._get_playlist_id_by_index(999)
        self.assertIsNone(playlist_id)


class TestParameters(unittest.TestCase):
    """Test cases for Parameters model."""

    def test_parameters_defaults(self) -> None:
        """Test Parameters model has correct defaults."""
        params = Parameters()

        self.assertIsNone(params.playlist_index)
        self.assertEqual(params.playlists, [])
        self.assertEqual(params.devices, [])
        self.assertIsNone(params.target_device)
        self.assertIsNone(params.volume)
        self.assertEqual(params.current_room, "")
        self.assertFalse(params.is_resume)

    def test_parameters_with_values(self) -> None:
        """Test Parameters model accepts values."""
        mock_device = create_mock_spotify_device()
        params = Parameters(
            playlist_index=1,
            playlists=[{"id": "123", "name": "Test"}],
            devices=[mock_device],
            target_device=mock_device,
            volume=50,
            current_room="bedroom",
            is_resume=True,
        )

        self.assertEqual(params.playlist_index, 1)
        self.assertEqual(len(params.playlists), 1)
        self.assertEqual(len(params.devices), 1)
        self.assertEqual(params.volume, 50)
        self.assertEqual(params.current_room, "bedroom")
        self.assertTrue(params.is_resume)


class TestSpotifyDevice(unittest.TestCase):
    """Test cases for SpotifyDevice model."""

    def test_from_global_device(self) -> None:
        """Test SpotifyDevice.from_global_device factory method."""
        mock_global_device = Mock(spec=GlobalDevice)
        mock_global_device.name = "Test Speaker"
        mock_global_device.room = Mock()
        mock_global_device.room.name = "bedroom"
        mock_global_device.device_attributes = {
            "spotify_id": "spotify_123",
            "is_main": True,
            "default_volume": 65,
        }

        spotify_device = models.SpotifyDevice.from_global_device(mock_global_device)

        self.assertEqual(spotify_device.name, "Test Speaker")
        self.assertEqual(spotify_device.room, "bedroom")
        self.assertEqual(spotify_device.spotify_id, "spotify_123")
        self.assertTrue(spotify_device.is_main)
        self.assertEqual(spotify_device.default_volume, 65)

    def test_from_global_device_with_defaults(self) -> None:
        """Test SpotifyDevice.from_global_device with missing attributes."""
        mock_global_device = Mock(spec=GlobalDevice)
        mock_global_device.name = "Test Speaker"
        mock_global_device.room = Mock()
        mock_global_device.room.name = "bedroom"
        mock_global_device.device_attributes = {}

        spotify_device = models.SpotifyDevice.from_global_device(mock_global_device)

        self.assertEqual(spotify_device.spotify_id, "")
        self.assertFalse(spotify_device.is_main)
        self.assertEqual(spotify_device.default_volume, 55)
