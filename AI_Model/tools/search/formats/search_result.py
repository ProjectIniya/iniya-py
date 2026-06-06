from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: Optional[float] = None
    extracted_content: Optional[str] = None

    semantic_score: float = 0.0
    authority_score: float = 0.0
    freshness_score: float = 0.0
    quality_score: float = 0.0
    spam_score: float = 0.0

    final_score: float = 0.0
    provider: str = ""