from tranco import Tranco
from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "cache" / "tranco"
if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class TrancoProvider(AuthorityProvider):
    name = "tranco"
    weight = 0.30

    def __init__(self):
        self.tranco = Tranco(
            cache=True,
            cache_dir=DATA_DIR
        )

        self.list = self.tranco.list()

    def normalize(self, rank):
        try:
            rank = int(rank)

            if rank <= 0:
                return 0.0

            score = 1 / (
                1 + math.log10(rank)
            )

            return max(
                0.0,
                min(score, 1.0)
            )

        except:
            return 0.0

    async def evaluate(self, domain , _):
        try:
            rank = self.list.rank(domain)

            return SignalResult(
                provider=self.name,
                score=self.normalize(rank),
                confidence=0.95,
                metadata={
                    "rank": rank
                }
            )

        except Exception as e:
            return SignalResult(
                provider=self.name,
                score=0.0,
                confidence=0.0,
                metadata={
                    "error": str(e)
                }
            )