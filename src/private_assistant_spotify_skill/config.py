import logging

import private_assistant_commons as commons

logger = logging.getLogger(__name__)


class SkillConfig(commons.SkillConfig):
    spotify_client_id: str
    spotify_client_secret: str
    redirect_uri: str
    scope: str = "user-read-playback-state user-modify-playback-state playlist-read-private"
