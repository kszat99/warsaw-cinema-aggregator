import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "monitor_booking_cutoffs.py"
SPEC = importlib.util.spec_from_file_location("monitor_booking_cutoffs", MODULE_PATH)
monitor_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor_module)
parse_rendered_seat_map = monitor_module.parse_rendered_seat_map
CutoffMonitor = monitor_module.CutoffMonitor


class RenderedSeatMapTests(unittest.TestCase):
    def test_cinema_city_counts_available_and_all_seats(self):
        html = """
        <svg>
          <g><rect class="seat-hit-area"/><use class="s a"/></g>
          <g><rect class="seat-hit-area"/><use class="s u"/></g>
        </svg>
        """
        result = parse_rendered_seat_map("cinema_city", html)
        self.assertEqual((result.state, result.available, result.capacity), ("open", 1, 2))

    def test_multikino_uses_status_one_as_unavailable(self):
        html = """
        <button class="seats__seat" data-seat-status="0-a"></button>
        <button class="seats__seat" data-seat-status="1-b"></button>
        <button class="seats__seat" data-seat-status="3-c"></button>
        """
        result = parse_rendered_seat_map("multikino", html)
        self.assertEqual((result.available, result.capacity, result.unavailable), (2, 3, 1))

    def test_helios_counts_double_seat_capacity(self):
        html = """
        <div class="screen-placeholder is-seat size-placeholder-1"></div>
        <div class="screen-placeholder is-seat size-placeholder-2"></div>
        <div class="seat free"></div><div class="seat free"></div>
        """
        result = parse_rendered_seat_map("helios", html)
        self.assertEqual((result.available, result.capacity, result.unavailable), (2, 3, 1))

    def test_missing_map_is_closed_but_network_errors_are_handled_elsewhere(self):
        result = parse_rendered_seat_map("multikino", "<p>Sprzedaż internetowa zakończona</p>")
        self.assertEqual(result.state, "closed")

    def test_amondo_counts_places_from_classic_svg_schema(self):
        seat_plan = {
            "classicSeatsPlanData": {
                "schema": (
                    '{"image":"<svg>'
                    '<path data-type=\\"place\\" data-row=\\"I\\" data-place=\\"1\\" />'
                    '<path data-type=\\"stage\\" />'
                    '<path data-type=\\"place\\" data-row=\\"I\\" data-place=\\"2\\" />'
                    '</svg>"}'
                )
            }
        }

        self.assertEqual(CutoffMonitor._count_amondo_seats(seat_plan), 2)

    def test_amondo_matches_nearest_repertoire_event(self):
        events = [
            {"id": 1, "startsAt": "2026-09-17T17:00:00+02:00"},
            {"id": 2, "startsAt": "2026-09-17T18:45:00+02:00"},
        ]
        target_start = monitor_module.datetime.fromisoformat("2026-09-17T18:45:00")

        self.assertEqual(CutoffMonitor._match_amondo_event(events, target_start)["id"], 2)


if __name__ == "__main__":
    unittest.main()
