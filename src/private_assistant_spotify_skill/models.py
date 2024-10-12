from sqlmodel import Field, SQLModel


class TokenCache(SQLModel, table=True):  # type: ignore
    id: int | None = Field(default=None, primary_key=True)
    token: str


class Device(SQLModel, table=True):  # type: ignore
    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str
    name: str
    room: str
    is_main: bool = Field(default=False)
    ip: str | None = Field(default=None)
