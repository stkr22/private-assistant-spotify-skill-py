"""Main entry point for the Spotify skill application.

This module provides the CLI interface and initialization logic for the Spotify skill.
Handles configuration loading, database setup, OAuth initialization, and skill startup.
"""

import asyncio
import pathlib
from typing import Annotated

import jinja2
import sqlmodel
import typer
from private_assistant_commons import mqtt_connection_handler, skill_config, skill_logger
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy.ext.asyncio import create_async_engine

from private_assistant_spotify_skill import config, db_cache_handler, spotify_skill

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

    Sets up logging, configuration, database engines, OAuth, templates, and
    starts the skill within the Private Assistant MQTT ecosystem.

    Args:
        config_path: Path to the YAML configuration file.

    Note:
        Uses dual database engines: sync for Spotipy's cache handler and
        async for the skill's database operations.
    """
    logger = skill_logger.SkillLogger.get_logger("Private Assistant SpotifySkill")

    # AIDEV-NOTE: Load skill-specific configuration extending base config
    config_obj = skill_config.load_config(config_path, config.SkillConfig)

    # AIDEV-NOTE: Sync engine required by Spotipy's cache handler
    db_engine = sqlmodel.create_engine(skill_config.PostgresConfig.from_env().connection_string)

    # Set up the cache handler for Spotify authentication
    cache_handler = db_cache_handler.DBCacheHandler(db_engine)

    # AIDEV-NOTE: Async engine for skill's async database operations
    db_engine_async = create_async_engine(skill_config.PostgresConfig.from_env().connection_string_async)

    # Initialize Spotify OAuth for authentication
    sp_oauth = SpotifyOAuth(
        client_id=config_obj.spotify_client_id,
        client_secret=config_obj.spotify_client_secret,
        redirect_uri=config_obj.redirect_uri,
        scope=config_obj.scope,
        cache_handler=cache_handler,
    )

    # Set up the Jinja2 environment for templating
    template_env = jinja2.Environment(
        loader=jinja2.PackageLoader(
            "private_assistant_spotify_skill",
            "templates",
        )
    )

    # AIDEV-NOTE: Start skill in Private Assistant ecosystem with MQTT
    await mqtt_connection_handler.mqtt_connection_handler(
        spotify_skill.SpotifySkill,
        config_obj,
        retry_interval=5,
        logger=logger,
        template_env=template_env,
        db_engine=db_engine_async,
        sp_oauth=sp_oauth,
    )


if __name__ == "__main__":
    app()
