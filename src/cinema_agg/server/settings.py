"""Explicit environment configuration, without automatic .env loading."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    database_path: Path = Path("data/cinema-development.sqlite3")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        values = {
            name.removeprefix("CINEMA_API_").lower(): value
            for name, value in os.environ.items()
            if name.startswith("CINEMA_API_")
        }
        return cls.model_validate(values)
