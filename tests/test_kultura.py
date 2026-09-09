import unittest
from datetime import date

import httpx

from src.cinema_agg.adapters.kultura import KulturaAdapter


class FakeClient:
    def __init__(self, html):
        self.html = html
        self.request = None

    async def get(self, url, **kwargs):
        self.request = (url, kwargs)
        return httpx.Response(200, text=self.html, request=httpx.Request("GET", url))


class KulturaAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_repertoire_and_removes_mobile_duplicate(self):
        item = """
        <div class="content_rep_posters_1b hand"
             onclick="rep_movie('123', '20782','15','0','2026-09-10','0','0','0','0');">
          <img alt="Tony" src="foto,20782,poster,jpg.html">
          <div>Kultura</div>
        </div>
        """
        client = FakeClient(item + item)
        adapter = KulturaAdapter(
            "kultura", "Kino Kultura", "https://www.kinokultura.pl/"
        )

        screenings = await adapter.fetch_screenings(date(2026, 9, 10), client)

        self.assertEqual(len(screenings), 1)
        screening = screenings[0]
        self.assertEqual(screening.title_raw, "Tony")
        self.assertEqual(screening.starts_at.isoformat(), "2026-09-10T15:00:00")
        self.assertEqual(screening.tags, ["Kultura"])
        self.assertEqual(
            screening.booking_url,
            "https://www.kinokultura.pl/repertuar/?date=2026-09-10",
        )
        self.assertEqual(
            screening.poster_url,
            "https://www.kinokultura.pl/foto,20782,poster,jpg.html",
        )
        self.assertEqual(
            client.request[1]["params"]["rep_date"], "2026-09-10"
        )


if __name__ == "__main__":
    unittest.main()
