import asyncio
import dns.resolver
from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult

class DNSProvider(AuthorityProvider):
    name = "dns"
    weight = 0.20

    async def evaluate(self, root_domain, hostname):
        checks = ["A", "AAAA", "CNAME", "MX"]

        async def check(record_type):
            try:
                await asyncio.to_thread(dns.resolver.resolve, hostname, record_type)
                return record_type
            except Exception:
                return None

        found = [r for r in await asyncio.gather(*[check(t) for t in checks]) if r]

        if "A" in found:        score = 1.0
        elif "AAAA" in found:   score = 0.9
        elif "CNAME" in found:  score = 0.7
        elif "MX" in found:     score = 0.5
        else:                   score = 0.0

        return SignalResult(
            provider=self.name, score=score, confidence=1.0,
            metadata={"records": found, "exists": len(found) > 0}
        )