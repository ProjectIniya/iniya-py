import asyncio
import ssl
import socket
from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult

class SSLProvider(AuthorityProvider):
    name = "ssl"
    weight = 0.10

    async def evaluate(self, _, hostname):
        try:
            result = await asyncio.to_thread(self._check_ssl, hostname)
            return result
        except Exception as e:
            return SignalResult(
                provider=self.name, score=0.2, confidence=0.5,
                metadata={"valid_ssl": False, "reason": "unknown", "error": str(e)}
            )

    def _check_ssl(self, hostname):
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as secure_sock:
                cert = secure_sock.getpeercert()
                issuer = dict(
                    x[0] for x in cert.get("issuer", [])
                ).get("organizationName")
                return SignalResult(
                    provider=self.name, score=0.6, confidence=0.9,
                    metadata={"valid_ssl": True, "issuer": issuer}
                )