# Private Assistant Spotify Skill Documentation

This documentation covers the implementation details and architectural decisions for the Spotify skill.

## Architecture Overview

The Spotify skill is built on the Private Assistant Commons framework and provides voice-controlled Spotify integration. The skill operates as an independent service that communicates via MQTT with other components in the ecosystem.

### Core Components

#### SpotifySkill Class
The main skill class that inherits from `BaseSkill` and implements:
- Voice command processing
- Spotify API integration
- Device and playlist management
- Template-based response generation

#### Models
- `Device`: Represents Spotify devices with room associations
- `TokenCache`: Stores OAuth tokens for stateless operation
- `Parameters`: Encapsulates command parameters for processing

#### Configuration
- `SkillConfig`: Extends base configuration with Spotify-specific settings
- Environment-based configuration for database and MQTT connections

## Command Processing Flow

1. **Intent Reception**: Skill receives `IntentAnalysisResult` via MQTT
2. **Certainty Calculation**: Checks for "spotify" keyword in nouns
3. **Action Matching**: Maps voice text to predefined actions using keyword matching
4. **Parameter Extraction**: Extracts numbers and context from the parsed intent
5. **Action Execution**: Performs Spotify API calls based on the action
6. **Response Generation**: Renders Jinja2 templates and sends MQTT response

## Action System

The skill uses an enum-based action system for command classification:

```python
class Action(enum.Enum):
    HELP = ["help"]
    LIST_PLAYLISTS = ["list", "playlists"]
    LIST_DEVICES = ["list", "devices"]
    PLAY_PLAYLIST = ["play", "playlist"]
    STOP_PLAYBACK = ["stop", "playback"]
    NEXT_TRACK = ["next", "track"]
    SET_VOLUME = ["set", "volume"]
    CONTINUE = ["continue"]
```

Each action maps to:
- Specific Spotify API operations
- Parameter extraction logic
- Jinja2 response templates

## Device Management

### Device Discovery
- Automatically discovers Spotify devices via API
- Parses device names with format: `room-devicename`
- Creates database entries for room associations
- Caches devices for performance

### Room-Aware Playback
- Identifies "main" devices per room
- Supports playback transfer between devices
- Enables room-specific voice commands

## Database Integration

### Dual Engine Approach
- **Sync Engine**: Used by Spotipy's cache handler for OAuth tokens
- **Async Engine**: Used by skill's async operations for device management

### Models
- Uses SQLModel for type-safe database operations
- Automatic table creation and migration support
- PostgreSQL backend for production deployments

## Template System

Response generation uses Jinja2 templates located in `src/private_assistant_spotify_skill/templates/`:

- `help.j2`: Command help information
- `list_playlists.j2`: Playlist enumeration
- `list_devices.j2`: Device enumeration
- `playback_started.j2`: Playback confirmation
- `playback_stopped.j2`: Stop confirmation
- `next_track.j2`: Skip confirmation
- `set_volume.j2`: Volume change confirmation
- `continue.j2`: Continue playback confirmation

## Error Handling

The skill implements comprehensive error handling:

- **Spotify API Errors**: Catches `SpotifyException` and logs specific error details
- **Generic Exceptions**: Catches unexpected errors with full stack traces
- **Parameter Validation**: Validates playlist/device indices before API calls
- **Graceful Degradation**: Continues operation even if individual commands fail

## Security Considerations

- OAuth tokens stored securely in database
- Volume limited to 90% maximum for hearing protection
- Input validation on all user-provided parameters
- No sensitive data in logs or responses

## Performance Optimizations

- **Caching**: Playlists and devices cached in memory
- **Async Operations**: All Spotify API calls use `asyncio.to_thread()`
- **Background Tasks**: Cache refresh runs independently
- **Connection Pooling**: Database connections managed by SQLAlchemy

## Deployment

The skill is designed for containerized deployment:

- Stateless operation with database-backed storage
- Environment variable configuration
- Health checks via MQTT connectivity
- Kubernetes-ready with proper resource management
