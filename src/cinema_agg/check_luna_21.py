import json
from datetime import datetime

def check_luna_21():
    try:
        with open("dist/showtimes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        luna_21 = [s for s in data["screenings"] if s["cinema_id"] == "luna" and "2026-02-21" in s["starts_at"]]
        
        print(f"Total Luna screenings on 2026-02-21 found: {len(luna_21)}")
        for s in luna_21:
            print(f"- {s['starts_at']} | {s['title_raw']}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_luna_21()
