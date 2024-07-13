import logging
import os
import pathlib
import sys
from typing import Annotated

import jinja2
import paho.mqtt.client as mqtt
import spacy
import sqlmodel
import typer
from spotipy.oauth2 import SpotifyOAuth

from private_assistant_spotify_skill import config, db_cache_handler, spotify_skill

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

app = typer.Typer()


@app.command()
def start_skill(
    config_path: Annotated[pathlib.Path, typer.Argument(envvar="PRIVATE_ASSISTANT_CONFIG_PATH")],
):
    config_obj = config.load_config(config_path)
    db_engine = sqlmodel.create_engine(config_obj.db_connection_string)
    cache_handler = db_cache_handler.DBCacheHandler(db_engine)
    sp_oauth = SpotifyOAuth(
        client_id=config_obj.spotify_client_id,
        client_secret=config_obj.spotify_client_secret,
        redirect_uri=config_obj.redirect_uri,
        scope=config_obj.scope,
        cache_handler=cache_handler,
    )
    spotify_skill_obj = spotify_skill.SpotifySkill(
        mqtt_client=mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=config_obj.client_id,
            protocol=mqtt.MQTTv5,
        ),
        config_obj=config_obj,
        nlp_model=spacy.load(config_obj.spacy_model),
        template_env=jinja2.Environment(
            loader=jinja2.PackageLoader(
                "private_assistant_spotify_skill",
                "templates",
            ),
        ),
        sp_oauth=sp_oauth,
        db_engine=db_engine,
    )
    spotify_skill_obj.run()


if __name__ == "__main__":
    start_skill(config_path=pathlib.Path("./local_config.yaml"))
