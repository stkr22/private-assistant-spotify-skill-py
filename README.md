# Private Assistant Spotify Skill

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![python](https://img.shields.io/badge/Python-3.12-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v0.json)](https://github.com/charliermarsh/ruff)
[![Checked with mypy](https://img.shields.io/static/v1?label=mypy&message=checked&color=blue)](https://mypy-lang.org/)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/format.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

Owner: stkr22

**READ THE CLAUDE.md**

A voice-controlled Spotify skill for the [Private Assistant](https://github.com/stkr22/private-assistant-commons-py) ecosystem. Control Spotify playback, manage playlists, and handle device switching through natural voice commands.

## Features

- **Voice Control**: Control Spotify through natural language commands
- **Playlist Management**: List and play your Spotify playlists by number
- **Device Management**: List available devices and switch playback between them
- **Playback Control**: Play, pause, skip tracks, and adjust volume
- **Room-Aware**: Automatically targets main devices in specific rooms
- **Stateless Operation**: Containerized deployment with database-backed token storage

## Supported Commands

| Command | Example | Description |
|---------|---------|-------------|
| List playlists | "list playlists" | Shows numbered list of your playlists |
| List devices | "list devices" | Shows numbered list of available Spotify devices |
| Play playlist | "play playlist 3 on device 2" | Plays playlist by number, optionally on specific device |
| Continue playback | "continue" | Resumes/transfers playback to room's main device |
| Stop playback | "stop playback" | Pauses current playback |
| Next track | "next track" | Skips to next song |
| Set volume | "set volume to 75" | Adjusts volume (max 90% for safety) |
| Help | "help" | Shows available commands |

## Quick Start

### Prerequisites

- Python 3.12+
- UV package manager
- Spotify Premium account
- Spotify application credentials
- PostgreSQL database
- MQTT broker

### Installation

```bash
# Clone the repository
git clone https://github.com/stkr22/private-assistant-spotify-skill-py.git
cd private-assistant-spotify-skill-py

# Install dependencies
uv sync --group dev

# Run tests
uv run pytest

# Format and lint
uv run ruff format .
uv run ruff check --fix .
uv run mypy src/
```

### Configuration

1. **Spotify App Setup**: Create a Spotify application at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

2. **Environment Variables**:
```bash
export PRIVATE_ASSISTANT_CONFIG_PATH=/path/to/config.yaml
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=private_assistant
export POSTGRES_USER=username
export POSTGRES_PASSWORD=password
```

3. **Configuration File** (`config.yaml`):
```yaml
mqtt_host: localhost
mqtt_port: 1883
mqtt_username: mqtt_user
mqtt_password: mqtt_pass
skill_name: spotify_skill
spotify_client_id: your_spotify_client_id
spotify_client_secret: your_spotify_client_secret
redirect_uri: http://localhost:8080/callback
scope: "user-read-playback-state user-modify-playback-state playlist-read-private"
```

### Running

```bash
# Start the skill
uv run private-assistant-spotify-skill /path/to/config.yaml

# Or use environment variable
PRIVATE_ASSISTANT_CONFIG_PATH=/path/to/config.yaml uv run private-assistant-spotify-skill
```

## Device Naming Convention

For automatic room detection, name your Spotify devices with the format: `room-devicename`

Examples:
- `living_room-speaker`
- `bedroom-echo_dot`
- `kitchen-mini`

The skill will parse the room name and create device entries in the database with proper room associations.

## Architecture

This skill integrates with the Private Assistant ecosystem using:

- **MQTT Communication**: Receives intent analysis results and sends responses
- **Async Processing**: Uses asyncio for concurrent operations
- **Database Caching**: Stores device mappings and OAuth tokens in PostgreSQL
- **Template Responses**: Jinja2 templates for dynamic response generation
- **Spotify API**: Spotipy library for Spotify Web API integration

## Development

See [CLAUDE.md](./CLAUDE.md) for detailed development guidelines and architectural decisions.

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=private_assistant_spotify_skill

# Run specific test file
uv run pytest tests/test_spotify_skill.py
```

### Contributing

1. Follow the coding standards in CLAUDE.md
2. Add tests for new functionality
3. Update documentation as needed
4. Use conventional commits with gitmoji

## License

GPL-3.0 - See [LICENSE](LICENSE) file for details.
