from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SignalResult:
    provider: str
    score: float
    confidence: float
    metadata: dict

class AuthorityProvider(ABC):
    name = "base"
    weight = 1.0

    @abstractmethod
    async def evaluate(self, domain: str, hostname: str) -> SignalResult:
        pass