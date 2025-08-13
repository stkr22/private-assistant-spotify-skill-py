"""Database-backed cache handler for Spotify OAuth tokens.

This module provides a Spotipy-compatible cache handler that stores OAuth tokens
in a PostgreSQL database instead of local files, enabling stateless deployment.
"""

import json
from typing import Any

import sqlalchemy
from spotipy.cache_handler import CacheHandler
from sqlmodel import Session, SQLModel, select

from private_assistant_spotify_skill.models import TokenCache


class DBCacheHandler(CacheHandler):
    """Database-backed cache handler for Spotify OAuth tokens.

    Implements Spotipy's CacheHandler interface to store OAuth tokens in a
    PostgreSQL database instead of local files. This enables stateless
    container deployment where OAuth state persists across restarts.

    Attributes:
        db_engine: SQLAlchemy database engine for token persistence.
    """

    def __init__(self, db_engine: sqlalchemy.Engine) -> None:
        """Initialize the cache handler with a database engine.

        Args:
            db_engine: SQLAlchemy engine for database operations.
        """
        self.db_engine = db_engine
        # AIDEV-NOTE: Ensure database tables exist before use
        SQLModel.metadata.create_all(self.db_engine)

    def get_cached_token(self) -> dict[str, Any] | None:
        """Retrieve the most recent cached token from the database.

        Returns:
            Parsed token dictionary or None if no token found.
        """
        with Session(self.db_engine) as session:
            # AIDEV-NOTE: Get most recent token by ID ordering
            statement = select(TokenCache).order_by(TokenCache.id.desc()).limit(1)  # type: ignore[union-attr]
            result = session.exec(statement).first()
            if result:
                return json.loads(result.token)  # type: ignore[no-any-return]
            return None

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        """Save OAuth token information to the database.

        Args:
            token_info: Token dictionary from Spotify OAuth flow.
        """
        token_json = json.dumps(token_info)
        with Session(self.db_engine) as session:
            token_cache = TokenCache(token=token_json)
            session.add(token_cache)
            session.commit()
            session.refresh(token_cache)

    def __del__(self) -> None:
        """Clean up database connections on object destruction."""
        self.db_engine.dispose()
