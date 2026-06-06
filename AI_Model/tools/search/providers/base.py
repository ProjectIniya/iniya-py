from abc import ABC, abstractmethod
from typing import List

from AI_Model.tools.search.formats.search_result import SearchResult


class BaseSearchProvider(ABC):

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5
    ) -> List[SearchResult]:
        pass