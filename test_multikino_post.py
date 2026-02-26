import httpx

url = "https://www.multikino.pl/api/sitecore/Showing/ShowingListing"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest"
}
data = {
    "cinemaId": "0040", # Warszawa Mlociny
    "date": "2026-02-22"
}

resp = httpx.post(url, data=data, headers=headers)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print(resp.text[:500])
else:
    print("Error getting showings.")
