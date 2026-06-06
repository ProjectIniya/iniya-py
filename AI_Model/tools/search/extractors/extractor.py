import asyncio
import trafilatura
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

class Extractor:

    async def extract(self, url: str) -> str | None:
        html = await self._fetch(url)

        if not html:
            return None

        extracted = trafilatura.extract(
            html,
            include_links=False,
            include_images=False,
            no_fallback=False,        # try harder before giving up
            favor_recall=True,        # extract more, filter less
        )

        return extracted

    async def _fetch(self, url: str) -> str | None:
        # try trafilatura's own fetcher first (handles more edge cases)
        try:
            html = await asyncio.to_thread(
                trafilatura.fetch_url, url
            )
            if html:
                return html
        except Exception:
            pass

        # fall back to httpx with browser headers
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=20,
                headers=HEADERS,
            ) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
        except Exception:
            pass

        return None