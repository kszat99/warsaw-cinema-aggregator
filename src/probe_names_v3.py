import httpx
import sys
import io
import re

async def probe_id(cid, client):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            # Look for the cinema name. It should be in the breadcrumbs or a header.
            # Usually it's in a <span class="cinema-name"> or something.
            # Let's just look for common names.
            text = resp.text
            if "Zielonka" in text: return "Zielonka"
            if "Galeria Północna" in text: return "Północna"
            if "Białołęka" in text: return "Białołęka"
            if "Arkadia" in text: return "Arkadia"
            if "Bemowo" in text: return "Bemowo"
            if "Promenada" in text: return "Promenada"
            if "Mokotów" in text: return "Mokotów"
            if "Janki" in text: return "Janki"
            if "Sadyba" in text: return "Sadyba"
            if "Manufaktura" in text: return "Manufaktura"
            
            # If not found, look for any text that looks like a name
            match = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.IGNORECASE)
            if match:
                return f"H1: {match.group(1).strip()}"
            
            return "Unknown (HTTP 200)"
        return f"HTTP {resp.status_code}"
    except Exception as e:
        return f"Ex: {e}"

import asyncio

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        # Probe IDs 1060 to 1100
        for cid in range(1060, 1101):
            name = await probe_id(cid, client)
            if "Unknown" not in name and "HTTP 404" not in name:
                print(f"ID {cid}: {name}")
            else:
                # Still print if it's 200 but unknown
                if "Unknown" in name:
                    print(f"ID {cid}: {name}")

if __name__ == "__main__":
    asyncio.run(main())
