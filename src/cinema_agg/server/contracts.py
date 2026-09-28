"""Legacy input validation and bounded public response contracts."""

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def utc_milliseconds(value: datetime, source_timezone: str) -> int:
    if value.tzinfo is None:
        zone = ZoneInfo(source_timezone)
        candidates = {
            value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            for fold in (0, 1)
            if value.replace(tzinfo=zone, fold=fold)
            .astimezone(UTC)
            .astimezone(zone)
            .replace(tzinfo=None)
            == value
        }
        if len(candidates) != 1:
            raise ValueError(
                "Ambiguous or nonexistent local time; supply an explicit offset."
            )
        value = candidates.pop()
    return int(value.timestamp() * 1000)


def utc_datetime(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, UTC)


class LegacyScreening(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    cinema_id: str = Field(min_length=1, max_length=100)
    cinema_name: str = Field(min_length=1, max_length=300)
    title_raw: str = Field(min_length=1, max_length=1000)
    title_norm: str = Field(min_length=1, max_length=1000)
    starts_at: datetime
    scraped_at: datetime
    duration_min: Annotated[int, Field(strict=True, gt=0, le=1440)] | None = None
    language: str = Field(default="org", max_length=100)
    tags: list[Annotated[str, Field(max_length=100)]] = Field(
        default_factory=list, max_length=30
    )
    booking_url: str | None = Field(default=None, max_length=8192)
    poster_url: str | None = Field(default=None, max_length=8192)

    @field_validator("duration_min", mode="before")
    @classmethod
    def unknown_legacy_duration(cls, value: object) -> object:
        # Legacy adapters use zero for an unknown runtime, not a zero-minute film.
        return None if type(value) is int and value == 0 else value

    @field_validator("booking_url", "poster_url")
    @classmethod
    def safe_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            info.field_name == "booking_url"
            and info.data.get("cinema_id") == "iluzjon"
            and not parsed.scheme
            and not parsed.netloc
            and value.startswith(("filmy/", "/filmy/", "repertuar/", "/repertuar/"))
        ):
            value = urljoin("https://www.iluzjon.fn.org.pl/", value)
            parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError(
                "Expected an HTTP(S) URL without credentials or whitespace."
            )
        return value


class LegacySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    generated_at: datetime
    screenings: list[LegacyScreening] = Field(min_length=1, max_length=50000)


class ScreeningView(LegacyScreening):
    id: str


class SnapshotView(BaseModel):
    id: str
    generated_at: datetime
    imported_at: datetime
    source_timezone: str
    row_count: int


class ScreeningPage(BaseModel):
    collection: dict[str, object] | None = None
    snapshot: SnapshotView | None
    total: int
    limit: int
    offset: int
    next_offset: int | None
    screenings: list[ScreeningView]
