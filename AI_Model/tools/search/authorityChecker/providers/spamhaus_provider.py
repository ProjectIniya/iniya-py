import asyncio
import dns.resolver
from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult

class SpamhausProvider(AuthorityProvider):
    name = "spamhaus"
    weight = 0.25

    async def evaluate(self, domain, _):
        try:
            query = ".".join(reversed(domain.split(".")))

            await asyncio.to_thread(
                dns.resolver.resolve,
                f"{query}.dbl.spamhaus.org",
                "A"
            )

            return SignalResult(
                provider=self.name, score=0.0, confidence=1.0,
                metadata={"listed": True}
            )
        except:
            return SignalResult(
                provider=self.name, score=0.5, confidence=0.9,
                metadata={"listed": False}
            )