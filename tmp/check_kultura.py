import httpx
import re

async def main():
    async with httpx.AsyncClient() as client:
        r = await client.get('https://www.kinokultura.pl/repertuar/', follow_redirects=True)
        iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', r.text, re.I)
        print("iFrames:", iframes)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
