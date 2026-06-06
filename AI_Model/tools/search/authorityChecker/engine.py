import asyncio
from urllib.parse import urlparse
import tldextract

from AI_Model.tools.search.authorityChecker.providers.tranco_provider import TrancoProvider
from AI_Model.tools.search.authorityChecker.providers.umbrella_provider import UmbrellaProvider
from AI_Model.tools.search.authorityChecker.providers.whois_provider import WhoisProvider
from AI_Model.tools.search.authorityChecker.providers.spamhaus_provider import SpamhausProvider
from AI_Model.tools.search.authorityChecker.providers.ssl_provider import SSLProvider
from AI_Model.tools.search.authorityChecker.providers.dns_provider import DNSProvider
from AI_Model.tools.search.authorityChecker.providers.base import SignalResult

class AuthorityEngine:
    def __init__(self):
        self.providers = [
            TrancoProvider(),
            UmbrellaProvider(),
            WhoisProvider(),
            SpamhausProvider(),
            SSLProvider(),
            DNSProvider()
        ]

    def normalize(self, url):
        parsed = urlparse(url)

        hostname = parsed.hostname

        if not hostname:
            raise ValueError(
                f"Invalid URL: {url}"
            )

        hostname = hostname.lower()

        ext = tldextract.extract(hostname)

        if not ext.domain or not ext.suffix:
            raise ValueError(
                f"Invalid domain: {url}"
            )

        root_domain = (
            f"{ext.domain}.{ext.suffix}"
        )

        return {
            "hostname": hostname,
            "root_domain": root_domain
        }
  
    async def safe_provider(self, provider, domain, hostname):
        try:
            return await asyncio.wait_for(
                provider.evaluate(domain, hostname),
                timeout=20          # raised from 8
            )
        except asyncio.TimeoutError:
            return SignalResult(
                provider=provider.name,
                score=0.0, confidence=0.0,
                metadata={"error": "timeout"}
            )
        except Exception as e:
            return SignalResult(
                provider=provider.name,
                score=0.0, confidence=0.0,
                metadata={"error": str(e)}
            )

    async def analyze(self, url):
        normalized = self.normalize(url)
        hostname = normalized["hostname"]
        root_domain = normalized["root_domain"]

        results = await asyncio.gather(*[
            self.safe_provider(p, root_domain, hostname)
            for p in self.providers
        ])

        total_weight = 0
        total_score = 0

        for p, r in zip(self.providers, results):
            effective_weight = (
                p.weight * r.confidence
            )

            total_score += (
                r.score * effective_weight
            )

            total_weight += effective_weight

        if total_weight == 0:
            final_score = 0.0
        else:
            final_score = (
                total_score / total_weight
            )

        return {
            "domain": root_domain,
            "hostname": hostname,
            "authority_score": round(final_score, 3),
            "signals": [
                r.__dict__
                for r in results
            ]
        }