import asyncio

from ddgs import DDGS

from AI_Model.tools.search.providers.base import BaseSearchProvider
from AI_Model.tools.search.formats.search_result import SearchResult


class DuckDuckGoProvider(BaseSearchProvider):

    async def search(self, query: str, max_results: int = 5):

        results = []

        def _sync():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        
        items = await asyncio.to_thread(_sync)

        for item in items:

            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    content=item.get("body", ""),
                    provider="duckduckgo"
                )
            )
        
        return results