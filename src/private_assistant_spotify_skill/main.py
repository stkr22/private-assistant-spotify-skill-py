"""Main entry point for the Spotify skill application.

This module provides the CLI interface and initialization logic for the Spotify skill.
Handles configuration loading, database setup, Redis OAuth caching, and skill startup.
"""

import asyncio
import pathlib
from typing import Annotated

import jinja2
import redis
import typer
from private_assistant_commons import mqtt_connection_handler, skill_config, skill_logger
from private_assistant_commons.database import PostgresConfig
from spotipy.cache_handler import RedisCacheHandler
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from private_assistant_spotify_skill import config, spotify_skill

app = typer.Typer()


@app.command()
def main(config_path: Annotated[pathlib.Path, typer.Argument(envvar="PRIVATE_ASSISTANT_CONFIG_PATH")]) -> None:
    """Start the Spotify skill with the given configuration.

    Args:
        config_path: Path to YAML configuration file or from PRIVATE_ASSISTANT_CONFIG_PATH env var.
    """
    asyncio.run(start_skill(config_path))


async def start_skill(config_path: pathlib.Path) -> None:
    """Initialize and start the Spotify skill with all required dependencies.

    Sets up logging, configuration, database engine, Redis cache, OAuth, templates,
    and starts the skill within the Private Assistant MQTT ecosystem.

    Args:
        config_path: Path to the YAML configuration file.
    """
    logger = skill_logger.SkillLogger.get_logger("Private Assistant SpotifySkill")

    # AIDEV-NOTE: Load skill-specific configuration extending base config
    config_obj = skill_config.load_config(config_path, config.SkillConfig)

    # AIDEV-NOTE: Single async engine for skill database operations (passed to BaseSkill)
    db_engine_async = create_async_engine(PostgresConfig().connection_string_async)

    # AIDEV-NOTE: Create database tables on startup (global device registry tables from commons)
    async with db_engine_async.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # AIDEV-NOTE: Redis cache for Spotify OAuth tokens (replaces PostgreSQL-based DBCacheHandler)
    redis_client = redis.from_url(config_obj.redis.url)
    cache_handler = RedisCacheHandler(redis=redis_client, key="spotify_token")

    # Initialize Spotify OAuth for authentication
    sp_oauth = SpotifyOAuth(
        client_id=config_obj.spotify.client_id,
        client_secret=config_obj.spotify.client_secret,
        redirect_uri=config_obj.spotify.redirect_uri,
        scope=config_obj.spotify.scope,
        cache_handler=cache_handler,
    )

    # Set up the Jinja2 environment for templating
    template_env = jinja2.Environment(
        loader=jinja2.PackageLoader(
            "private_assistant_spotify_skill",
            "templates",
        )
    )

    # AIDEV-NOTE: Dependencies container for clean dependency injection
    dependencies = spotify_skill.SpotifySkillDependencies(
        db_engine=db_engine_async,
        template_env=template_env,
        sp_oauth=sp_oauth,
    )

    # AIDEV-NOTE: Start skill in Private Assistant ecosystem with MQTT
    await mqtt_connection_handler.mqtt_connection_handler(
        spotify_skill.SpotifySkill,
        config_obj,
        retry_interval=5,
        logger=logger,
        dependencies=dependencies,
    )


if __name__ == "__main__":
    app()
