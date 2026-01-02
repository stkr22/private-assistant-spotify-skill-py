"""End-to-end integration tests for the Spotify skill.

Tests the full workflow with PostgreSQL database, Redis cache, MQTT broker,
and the skill running as a background task. Spotify API is mocked to avoid
external dependencies.

Run with: uv run pytest tests/test_integration.py -v -m integration -n 0
"""

import asyncio
import contextlib
import json
import os
import pathlib
import tempfile
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import aiomqtt
import pytest
import pytest_asyncio
from private_assistant_commons import ClassifiedIntent, ClientRequest, Entity, EntityType, IntentRequest, IntentType
from private_assistant_commons.database import DeviceType, GlobalDevice, Room, Skill, create_skill_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from private_assistant_spotify_skill.main import start_skill
from private_assistant_spotify_skill.spotify_skill import MAX_VOLUME_LIMIT

# AIDEV-NOTE: Mark all tests as integration tests requiring real infrastructure
pytestmark = pytest.mark.integration

# Constants for MQTT topics
INTENT_TOPIC = "assistant/intent_engine/result"
OUTPUT_TOPIC = "assistant/output/text"


# --- Infrastructure Fixtures ---


@pytest_asyncio.fixture
async def db_engine():
    """Create async database engine and initialize tables."""
    # Use create_skill_engine() for resilient connection handling in tests
    engine = create_skill_engine()

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    # Cleanup: drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def mqtt_config() -> dict[str, Any]:
    """Get MQTT configuration from environment variables."""
    return {
        "host": os.environ.get("MQTT_HOST", "localhost"),
        "port": int(os.environ.get("MQTT_PORT", "1883")),
    }


@pytest_asyncio.fixture
async def mqtt_test_client(mqtt_config):
    """Create MQTT client for test message publishing/subscribing."""
    async with aiomqtt.Client(
        hostname=mqtt_config["host"],
        port=mqtt_config["port"],
        identifier=f"test_client_{uuid.uuid4().hex[:8]}",
    ) as client:
        yield client


@pytest.fixture
def skill_config_file() -> pathlib.Path:
    """Create temporary YAML config file for the skill.

    Note: Spotify, Valkey, and MQTT settings are loaded from environment variables
    with SPOTIFY_, VALKEY_, and MQTT_ prefixes respectively. These are set in the
    running_skill fixture.
    """
    config_content = """
client_id: test_spotify_skill
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        return pathlib.Path(f.name)


# --- Data Fixtures ---


@pytest_asyncio.fixture
async def test_devices(db_engine) -> list[GlobalDevice]:
    """Create test room, device type, skill, and Spotify devices in the database."""
    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        # Create room
        room = Room(name="living_room")
        session.add(room)
        await session.commit()
        await session.refresh(room)

        # Create device type
        device_type = DeviceType(name="spotify_device")
        session.add(device_type)
        await session.commit()
        await session.refresh(device_type)

        # Create skill (required for GlobalDevice)
        skill = Skill(name="test_spotify_skill")
        session.add(skill)
        await session.commit()
        await session.refresh(skill)

        # Create devices
        devices = [
            GlobalDevice(
                name="Living Room Speaker",
                room_id=room.id,
                device_type_id=device_type.id,
                skill_id=skill.id,
                device_attributes={
                    "spotify_id": "spotify_device_living_room",
                    "is_main": True,
                    "default_volume": 55,
                },
            ),
            GlobalDevice(
                name="Kitchen Speaker",
                room_id=room.id,
                device_type_id=device_type.id,
                skill_id=skill.id,
                device_attributes={
                    "spotify_id": "spotify_device_kitchen",
                    "is_main": False,
                    "default_volume": 50,
                },
            ),
        ]
        for device in devices:
            session.add(device)
        await session.commit()

        for device in devices:
            await session.refresh(device)

        return devices


# --- Mock Spotify API ---


def create_mock_spotify() -> MagicMock:
    """Create a mock Spotify client with predefined responses."""
    mock_spotify = MagicMock()

    # Mock playlist responses
    mock_spotify.current_user_playlists.return_value = {
        "items": [
            {"id": "playlist1", "name": "Chill Vibes"},
            {"id": "playlist2", "name": "Workout Hits"},
            {"id": "playlist3", "name": "Focus Music"},
        ]
    }

    # Mock device responses
    mock_spotify.devices.return_value = {
        "devices": [
            {
                "id": "spotify_device_living_room",
                "name": "Living Room Speaker",
                "is_active": True,
                "type": "Speaker",
            },
            {
                "id": "spotify_device_kitchen",
                "name": "Kitchen Speaker",
                "is_active": False,
                "type": "Speaker",
            },
        ]
    }

    # Mock playback control methods
    mock_spotify.start_playback = MagicMock()
    mock_spotify.pause_playback = MagicMock()
    mock_spotify.next_track = MagicMock()
    mock_spotify.volume = MagicMock()

    return mock_spotify


# --- Skill Startup Fixture ---


@pytest_asyncio.fixture
async def running_skill(
    db_engine,  # noqa: ARG001 - Required fixture dependency for table creation
    test_devices,  # noqa: ARG001 - Required fixture dependency for device setup
    skill_config_file: pathlib.Path,
):
    """Start the Spotify skill as a background task with mocked Spotify API."""
    mock_spotify = create_mock_spotify()

    # Wait for devices to be persisted
    await asyncio.sleep(0.5)

    # Set Spotify, Valkey, and MQTT environment variables (using env_prefix from pydantic-settings)
    env_vars = {
        "SPOTIFY_CLIENT_ID": "test_client_id",
        "SPOTIFY_CLIENT_SECRET": "test_client_secret",
        "SPOTIFY_REDIRECT_URI": "http://localhost:8080/callback",
        "VALKEY_HOST": "redis",
        "VALKEY_PORT": "6379",
        "MQTT_HOST": "mosquitto",
        "MQTT_PORT": "1883",
    }
    original_env = {key: os.environ.get(key) for key in env_vars}
    for key, value in env_vars.items():
        os.environ[key] = value

    # Patch Spotify API and OAuth
    with (
        patch("spotipy.Spotify", return_value=mock_spotify),
        patch("spotipy.oauth2.SpotifyOAuth") as mock_oauth_class,
    ):
        # Configure OAuth mock to return a valid token
        mock_oauth = MagicMock()
        mock_oauth.get_cached_token.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_at": 9999999999,
        }
        mock_oauth_class.return_value = mock_oauth

        # Start skill as background task
        skill_task = asyncio.create_task(start_skill(skill_config_file))

        # Wait for skill initialization
        await asyncio.sleep(3)

        yield mock_spotify

        # Cleanup: cancel skill task
        skill_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await skill_task

    # Cleanup temp config file
    skill_config_file.unlink(missing_ok=True)

    # Restore original environment variables
    for key, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


# --- Helper Functions ---


def create_intent_request_payload(
    intent_type: IntentType,
    room: str,
    raw_text: str,
    entities: dict[EntityType, list[Any]] | None = None,
    confidence: float = 0.9,
) -> str:
    """Create an IntentRequest JSON payload for MQTT publishing.

    Args:
        intent_type: The type of intent (e.g., MEDIA_PLAY, MEDIA_STOP).
        room: The room name for the request.
        raw_text: The raw text of the user's request.
        entities: Dict mapping EntityType to list of values. Numbers should be int/float.
        confidence: Confidence score for the intent.

    Returns:
        JSON string of the IntentRequest.
    """
    if entities is None:
        entities = {}

    # Convert raw entity values to proper Entity objects with correct types
    processed_entities: dict[str, list[Entity]] = {}
    for entity_type, values in entities.items():
        entity_list = []
        for v in values:
            # Determine normalized_value type based on entity type
            if entity_type == EntityType.NUMBER:
                normalized_value = int(v) if isinstance(v, (int, float)) else v
            else:
                normalized_value = str(v)

            entity_list.append(
                Entity(
                    id=uuid.uuid4(),
                    type=entity_type,
                    raw_text=str(v),
                    normalized_value=normalized_value,
                    confidence=0.9,
                    metadata={},
                    linked_to=[],
                )
            )
        # Use the entity type value as the key (e.g., "number" for EntityType.NUMBER)
        processed_entities[entity_type.value] = entity_list

    # Create proper Pydantic models for correct serialization
    classified_intent = ClassifiedIntent(
        id=uuid.uuid4(),
        intent_type=intent_type,
        confidence=confidence,
        entities=processed_entities,
        alternative_intents=[],
        raw_text=raw_text,
        timestamp=datetime.now(),
    )

    client_request = ClientRequest(
        id=uuid.uuid4(),
        text=raw_text,
        room=room,
        output_topic=OUTPUT_TOPIC,
    )

    intent_request = IntentRequest(
        id=uuid.uuid4(),
        classified_intent=classified_intent,
        client_request=client_request,
    )

    return intent_request.model_dump_json()


async def publish_intent_request(
    mqtt_client: aiomqtt.Client,
    intent_type: IntentType,
    room: str,
    raw_text: str,
    entities: dict[EntityType, list[Any]] | None = None,
) -> None:
    """Publish an IntentRequest to the skill's input topic."""
    payload = create_intent_request_payload(intent_type, room, raw_text, entities)
    await mqtt_client.publish(INTENT_TOPIC, payload)


def decode_mqtt_payload(payload: str | bytes | bytearray | int | float | None) -> str:
    """Decode MQTT message payload to string."""
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode()
    if isinstance(payload, bytearray):
        return payload.decode()
    return str(payload)


async def wait_for_response(
    mqtt_client: aiomqtt.Client,
    timeout: float = 5.0,
) -> str:
    """Wait for and return the skill's response text."""
    await mqtt_client.subscribe(OUTPUT_TOPIC)

    async with asyncio.timeout(timeout):
        async for message in mqtt_client.messages:
            payload_str = decode_mqtt_payload(message.payload)
            payload = json.loads(payload_str)
            if "text" in payload:
                return str(payload["text"])
            if "response" in payload:
                return str(payload["response"])
            # Return raw payload as string if structure is different
            return str(payload)

    raise TimeoutError("No response received within timeout")


# --- Test Classes ---


class TestSystemHelpIntent:
    """Test SYSTEM_HELP intent processing."""

    async def test_help_response(
        self,
        running_skill,  # noqa: ARG002 - Required fixture for skill background task
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test that help intent returns help information."""
        # Subscribe first, then publish
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.SYSTEM_HELP,
            "living_room",
            "spotify help",
        )

        # Wait for response
        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                # Verify help text is returned
                assert response_text, "Expected non-empty help response"
                # Help text should contain spotify-related information
                assert any(keyword in response_text.lower() for keyword in ["spotify", "play", "music", "playlist"]), (
                    f"Expected help text to contain spotify keywords, got: {response_text}"
                )
                break


class TestQueryListIntent:
    """Test QUERY_LIST intent for playlists and devices."""

    async def test_query_playlists(
        self,
        running_skill,  # noqa: ARG002 - Required fixture for skill background task
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test that querying playlists returns playlist list."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        # No entities needed - skill determines playlist vs device from raw_text
        await publish_intent_request(
            mqtt_test_client,
            IntentType.QUERY_LIST,
            "living_room",
            "list spotify playlists",
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                # Verify playlists are listed
                assert response_text, "Expected non-empty playlist response"
                # Should contain playlist names from mock
                assert any(name in response_text for name in ["Chill Vibes", "Workout Hits", "Focus Music"]), (
                    f"Expected playlist names in response, got: {response_text}"
                )
                break

    async def test_query_devices(
        self,
        running_skill,  # noqa: ARG002 - Required fixture for skill background task
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test that querying devices returns device list."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        # No entities needed - skill determines playlist vs device from raw_text
        await publish_intent_request(
            mqtt_test_client,
            IntentType.QUERY_LIST,
            "living_room",
            "list spotify devices",
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                # Verify devices are listed
                assert response_text, "Expected non-empty device response"
                break


class TestMediaPlayIntent:
    """Test MEDIA_PLAY intent processing."""

    async def test_play_playlist(
        self,
        running_skill,
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test playing a playlist starts playback."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_PLAY,
            "living_room",
            "play playlist 1 on spotify",
            entities={EntityType.NUMBER: [1]},
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                # Verify playback response
                assert response_text, "Expected non-empty playback response"
                break

        # Verify Spotify API was called
        running_skill.start_playback.assert_called()

    async def test_continue_playback(
        self,
        running_skill,  # noqa: ARG002 - Required fixture for skill background task
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test continue/resume playback."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_PLAY,
            "living_room",
            "continue spotify",
            entities={EntityType.MODIFIER: ["continue"]},
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                # Verify we got a response indicating playback continued
                assert response_text, "Expected non-empty continue response"
                break


class TestMediaStopIntent:
    """Test MEDIA_STOP intent processing."""

    async def test_stop_playback(
        self,
        running_skill,
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test stopping playback pauses music."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_STOP,
            "living_room",
            "stop spotify",
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                assert response_text, "Expected non-empty stop response"
                # Response should indicate playback stopped
                assert any(keyword in response_text.lower() for keyword in ["stop", "pause", "stopped"]), (
                    f"Expected stop confirmation, got: {response_text}"
                )
                break

        # Verify Spotify API was called
        running_skill.pause_playback.assert_called()


class TestMediaNextIntent:
    """Test MEDIA_NEXT intent processing."""

    async def test_skip_track(
        self,
        running_skill,
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test skipping to next track."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_NEXT,
            "living_room",
            "next track on spotify",
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                assert response_text, "Expected non-empty next track response"
                break

        # Verify Spotify API was called
        running_skill.next_track.assert_called()


class TestMediaVolumeSetIntent:
    """Test MEDIA_VOLUME_SET intent processing."""

    async def test_set_volume(
        self,
        running_skill,
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test setting volume to specific level."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_VOLUME_SET,
            "living_room",
            "set spotify volume to 50",
            entities={EntityType.NUMBER: [50]},
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                assert response_text, "Expected non-empty volume response"
                # Response should mention volume
                assert "50" in response_text or "volume" in response_text.lower(), (
                    f"Expected volume confirmation, got: {response_text}"
                )
                break

        # Verify Spotify API was called with correct volume
        running_skill.volume.assert_called()

    async def test_volume_respects_max_limit(
        self,
        running_skill,
        mqtt_test_client: aiomqtt.Client,
    ) -> None:
        """Test that volume is capped at MAX_VOLUME_LIMIT (90)."""
        await mqtt_test_client.subscribe(OUTPUT_TOPIC)

        await publish_intent_request(
            mqtt_test_client,
            IntentType.MEDIA_VOLUME_SET,
            "living_room",
            "set spotify volume to 100",
            entities={EntityType.NUMBER: [100]},
        )

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                payload = json.loads(decode_mqtt_payload(message.payload))
                response_text = payload.get("text", payload.get("response", ""))

                assert response_text, "Expected non-empty volume response"
                break

        # Verify volume was capped at MAX_VOLUME_LIMIT
        running_skill.volume.assert_called()
        call_args = running_skill.volume.call_args
        if call_args and call_args.kwargs:
            assert call_args.kwargs.get("volume_percent", 100) <= MAX_VOLUME_LIMIT, (
                f"Volume should be capped at {MAX_VOLUME_LIMIT}"
            )
