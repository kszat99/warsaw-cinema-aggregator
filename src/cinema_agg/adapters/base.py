import httpx
from abc import ABC, abstractmethod
from datetime import date
from typing import List
from ..models import Screening

class BaseAdapter(ABC):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str):
        self.cinema_id = cinema_id
        self.cinema_name = cinema_name
        self.base_url = base_url

    @abstractmethod
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        """Fetch and parse screenings for a specific date."""
        pass
