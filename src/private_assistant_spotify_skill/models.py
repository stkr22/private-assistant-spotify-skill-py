from sqlmodel import Field, SQLModel


class TokenCache(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token: str


class Device(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str
    name: str
    room: str
    is_main: bool = False
    default_volume: int = 55
    ip: str | None = None
