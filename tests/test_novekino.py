import unittest
from datetime import date

import httpx

from src.cinema_agg.adapters.novekino import NovekinoAdapter
from src.cinema_agg.normalize import normalize_title


class FakeClient:
    def __init__(self, html):
        self.html = html

    async def get(self, url, follow_redirects=True):
        return httpx.Response(200, text=self.html, request=httpx.Request("GET", url))


class NovekinoAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_new_msi_link_class_without_mobile_duplicate(self):
        html = """
        <div class="movies-movie">
          <div class="movies-movie__single__poster">
            <img src="/MSI/ImageData.ashx?id=3170&amp;mode=thumb">
          </div>
          <h3 class="movies-movie__single__title">Example Film (Kultura)</h3>
          <ul class="movies-movie__single__moreinfo"><li>czas: 72 min.</li></ul>
          <a class="js-link-popup" data-event="53186"
             href="/MSI/Default.aspx?event_id=53186&amp;typetran=1">14:30</a>
          <a class="js-link-popup" data-event="53186"
             href="/MSI/Default.aspx?event_id=53186&amp;typetran=1">14:30</a>
        </div>
        """
        adapter = NovekinoAdapter(
            "kultura", "Kino Kultura", "https://rezerwacja.kinokultura.pl/MSI/mvc/pl"
        )

        screenings = await adapter.fetch_screenings(date(2026, 8, 21), FakeClient(html))

        self.assertEqual(len(screenings), 1)
        self.assertEqual(screenings[0].starts_at.isoformat(), "2026-08-21T14:30:00")
        self.assertEqual(screenings[0].duration_min, 72)
        self.assertIn("OrderTickets.aspx", screenings[0].booking_url)
        self.assertIn("typetran=0", screenings[0].booking_url)
        self.assertEqual(
            screenings[0].poster_url,
            "https://rezerwacja.kinokultura.pl/MSI/ImageData.ashx?id=3170&mode=thumb",
        )

    async def test_keeps_old_msi_link_class_compatible(self):
        html = """
        <div class="movies-movie">
          <h2 class="movies-movie__single__title">Legacy Film</h2>
          <a class="js-repo-popup" href="/MSI/Default.aspx?event_id=1">18:00</a>
        </div>
        """
        adapter = NovekinoAdapter("wisla", "Novekino Wisła", "https://wisla.novekino.pl/MSI/mvc/pl")

        screenings = await adapter.fetch_screenings(date(2026, 8, 21), FakeClient(html))

        self.assertEqual(len(screenings), 1)
        self.assertEqual(screenings[0].starts_at.isoformat(), "2026-08-21T18:00:00")


class NormalizeTitleTests(unittest.TestCase):
    def test_periods_with_or_without_following_spaces_group_together(self):
        self.assertEqual(
            normalize_title("Arek. Mama. Panorama"),
            normalize_title("Arek.Mama.Panorama"),
        )
        self.assertEqual(normalize_title("Arek.Mama.Panorama"), "arek mama panorama")

    def test_hyphenated_and_spaced_title_group_together(self):
        self.assertEqual(normalize_title("Spider-Man"), normalize_title("Spider Man"))


if __name__ == "__main__":
    unittest.main()
