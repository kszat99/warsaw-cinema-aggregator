import httpx
import sys
import io
from datetime import datetime, timedelta

# Fix python print unicode error in Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = "https://www.multikino.pl/repertuar/warszawa-mlociny/teraz-gramy"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

with httpx.Client(headers=headers, follow_redirects=True) as client:
    client.get(url)  # Get cookies
    
    target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    
    api_url = "https://www.multikino.pl/api/microservice/showings/cinemas/0040/films"
    params = {
        "showingDate": target_date,
        "minEmbargoLevel": "3",
        "includesSession": "true",
        "includeSessionAttributes": "true"
    }
    
    api_resp = client.get(api_url, params=params)
    data = api_resp.json()
    
    if "result" in data and isinstance(data["result"], list):
        films = data["result"]
        
        for film in films[:1]:
            groups = film.get("showingGroups", [])
            for g in groups:
                sessions = g.get("sessions", [])
                for s in sessions[:1]:
                    print("Session keys:", list(s.keys()))
                    print("Session time key mapping:", s)
