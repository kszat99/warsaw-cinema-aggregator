import json
from collections import Counter
from datetime import datetime
import os

def generate_report():
    file_path = "dist/showtimes.json"
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    screenings = data.get("screenings", [])
    
    # Grouping: (cinema_name, date_str) -> count
    stats = Counter()
    dates = set()
    cinemas = set()

    for s in screenings:
        cinema = s["cinema_name"]
        # starts_at is ISO: 2026-02-18T14:45:00
        dt_str = s["starts_at"].split("T")[0]
        stats[(cinema, dt_str)] += 1
        dates.add(dt_str)
        cinemas.add(cinema)

    sorted_dates = sorted(list(dates))
    sorted_cinemas = sorted(list(cinemas))

    # Header
    header = f"{'Cinema':<25}"
    for d in sorted_dates:
        header += f" | {d}"
    print(header)
    print("-" * len(header))

    for c in sorted_cinemas:
        row = f"{c:<25}"
        for d in sorted_dates:
            count = stats.get((c, d), 0)
            row += f" | {count:^10}"
        print(row)

    print("\nTotal screenings:", len(screenings))

if __name__ == "__main__":
    generate_report()
