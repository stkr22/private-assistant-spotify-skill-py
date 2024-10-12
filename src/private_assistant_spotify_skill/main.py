import asyncio
import pathlib
from typing import Annotated

import jinja2
import sqlmodel
import typer
from private_assistant_commons import async_typer, mqtt_connection_handler, skill_config, skill_logger
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy.ext.asyncio import create_async_engine

from private_assistant_spotify_skill import config, db_cache_handler, spotify_skill

app = async_typer.AsyncTyper()


@app.async_command()
async def start_skill(
    config_path: Annotated[pathlib.Path, typer.Argument(envvar="PRIVATE_ASSISTANT_CONFIG_PATH")],
):
    logger = skill_logger.SkillLogger.get_logger("Private Assistant SpotifySkill")
    # Load the configuration
    config_obj = skill_config.load_config(config_path, config.SkillConfig)

    # Set up the database engine
    db_engine = sqlmodel.create_engine(skill_config.PostgresConfig.from_env().connection_string)

    # Set up the cache handler for Spotify authentication
    cache_handler = db_cache_handler.DBCacheHandler(db_engine)

    # Create an async database engine
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
    # Start the skill using the async MQTT connection handler
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
    asyncio.get_event_loop().run_until_complete(start_skill(config_path=pathlib.Path("./local_config.yaml")))
