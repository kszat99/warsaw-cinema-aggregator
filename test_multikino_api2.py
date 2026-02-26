import httpx

url = "https://www.multikino.pl/api/sitecore/Showing/ShowingListing"
# It usually requires a POST Request with form data, maybe? Let's try GET first
params = {
    "cinemaId": "0040", # Mlociny maybe ? 
    "date": "2026-02-22"
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

resp = httpx.get(url, params=params, headers=headers)
print(f"GET Status: {resp.status_code}")
print(resp.text[:500])

resp2 = httpx.post(url, data=params, headers=headers)
print(f"POST Status: {resp2.status_code}")
print(resp2.text[:500])
