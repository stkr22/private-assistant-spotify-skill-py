import json

import sqlalchemy
from spotipy.cache_handler import CacheHandler
from sqlmodel import Session, SQLModel, select

from private_assistant_spotify_skill.models import TokenCache


class DBCacheHandler(CacheHandler):
    def __init__(self, db_engine: sqlalchemy.Engine):
        self.db_engine = db_engine
        SQLModel.metadata.create_all(self.db_engine)

    def get_cached_token(self):
        with Session(self.db_engine) as session:
            statement = select(TokenCache).order_by(TokenCache.id.desc()).limit(1)
            result = session.exec(statement).first()
            if result:
                return json.loads(result.token)
            return None

    def save_token_to_cache(self, token_info):
        token_json = json.dumps(token_info)
        with Session(self.db_engine) as session:
            token_cache = TokenCache(token=token_json)
            session.add(token_cache)
            session.commit()
            session.refresh(token_cache)

    def __del__(self):
        self.db_engine.dispose()
