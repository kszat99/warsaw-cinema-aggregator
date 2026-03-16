import httpx
import asyncio
import sys
import io

async def check_id(cid, client):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        # Even if 404, we look for clues in the text
        text = resp.text.lower()
        results = []
        if "arkadia" in text: results.append("Arkadia")
        if "bemowo" in text: results.append("Bemowo")
        if "sadyba" in text: results.append("Sadyba")
        if "mokotów" in text: results.append("Mokotów")
        if "promenada" in text: results.append("Promenada")
        if "janki" in text: results.append("Janki")
        if "północna" in text: results.append("Północna")
        if "białołęka" in text: results.append("Białołęka")
        if "zielonka" in text: results.append("Zielonka")
        if "zielona góra" in text: results.append("Zielona Góra")
        if "manufaktura" in text: results.append("Manufaktura")
        if "łódź" in text: results.append("Łódź")
        
        # Also try to find a specific pattern like "data-cinema-name='...'"
        import re
        match = re.search(r'data-cinema-name=["\'](.*?)["\']', resp.text)
        if match:
            results.append(f"NAME: {match.group(1)}")
            
        if results:
            return f"ID {cid} ({resp.status_code}): " + ", ".join(set(results))
        return None
    except Exception as e:
        return f"ID {cid} Error: {e}"

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        print("Checking IDs 1060-1100...")
        tasks = [check_id(cid, client) for cid in range(1060, 1101)]
        responses = await asyncio.gather(*tasks)
        for r in responses:
            if r:
                print(r)

if __name__ == "__main__":
    asyncio.run(main())
