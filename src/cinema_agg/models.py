from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class Screening(BaseModel):
    cinema_id: str = Field(..., description="Unique identifier for the cinema (e.g., 'wisla', 'luna')")
    cinema_name: str = Field(..., description="Human-readable cinema name")
    title_raw: str = Field(..., description="Original movie title as seen on the website")
    title_norm: str = Field(..., description="Normalized movie title (lowercase, no special characters)")
    starts_at: datetime = Field(..., description="Full date and time of the screening")
    duration_min: Optional[int] = Field(None, description="Movie duration in minutes")
    language: str = Field("org", description="Language version: 'nap' (subtitles), 'dub' (dubbing), 'voiceover' (lektor), 'org' (original)")
    tags: List[str] = Field(default_factory=list, description="Additional tags like '3D', 'DKF', 'Special Event'")
    booking_url: Optional[str] = Field(None, description="Direct link to ticket purchase/reservation")
    poster_url: Optional[str] = Field(None, description="Movie poster URL from TMDB")
    scraped_at: datetime = Field(default_factory=datetime.now, description="When this data was fetched")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class Cinema(BaseModel):
    id: str
    name: str
    url: str
    adapter: str

class BuildOutput(BaseModel):
    generated_at: datetime
    screenings: List[Screening]
