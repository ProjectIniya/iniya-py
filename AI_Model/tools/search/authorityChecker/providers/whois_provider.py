import asyncio
import whois
from datetime import datetime, timezone
from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult

class WhoisProvider(AuthorityProvider):
    name = "whois"
    weight = 0.20

    async def evaluate(self, domain, _):
        try:
            data = await asyncio.to_thread(whois.whois, domain)

            creation = data.creation_date
            if isinstance(creation, list):
                creation = min(creation)

            if creation is None:
                return SignalResult(
                    provider=self.name, score=0.3, confidence=0.3,
                    metadata={"available": False, "reason": "no_creation_date"}
                )

            if creation.tzinfo is None:
                creation = creation.replace(tzinfo=timezone.utc)

            age_days = max((datetime.now(timezone.utc) - creation).days, 0)
            score = min(age_days / 3650, 1.0)

            return SignalResult(
                provider=self.name, score=score, confidence=0.8,
                metadata={"age_days": age_days, "registrar": data.registrar}
            )
        except Exception as e:
            return SignalResult(
                provider=self.name, score=0.0, confidence=0.0,
                metadata={"error": str(e).splitlines()[0][:200]}
            )