import asyncio

from tavily import TavilyClient

from AI_Model.tools.search.providers.base import BaseSearchProvider
from AI_Model.tools.search.formats.search_result import SearchResult


class TavilyProvider(BaseSearchProvider):

    def __init__(self, api_key: str):
        self.client = TavilyClient(api_key=api_key)

    async def search(self, query: str, max_results: int = 5):

        def _sync():
            return self.client.search(query=query, max_results=max_results)

        try:
            response = await asyncio.to_thread(_sync)
        except Exception as e:
            # 422 = bad key / quota, 401 = invalid key
            # Don't raise — let DuckDuckGo carry the search
            from AI_Model.log import log
            log(f"Tavily unavailable ({e}), falling back to DDGS.", "TOOLS WARN")
            return []

        results = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score"),
                    provider="tavily"
                )
            )

        return results