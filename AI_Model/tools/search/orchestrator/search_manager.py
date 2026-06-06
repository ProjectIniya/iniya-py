import asyncio

from AI_Model.tools.search.processing.deduplicator import Deduplicator
from AI_Model.tools.search.processing.cleaner import Cleaner


class SearchManager:

    def __init__(self, providers):
        self.providers = providers
        self.deduplicator = Deduplicator()
        self.cleaner = Cleaner()

    async def search(self, query: str, max_results: int = 5):
        results_sets = await asyncio.gather(
            *[p.search(query, max_results=max_results) for p in self.providers]
        )
        merged = [r for result_set in results_sets for r in result_set]
        deduped = self.deduplicator.deduplicate(merged)
        for r in deduped:
            r.content = self.cleaner.clean(r.content)
        return deduped