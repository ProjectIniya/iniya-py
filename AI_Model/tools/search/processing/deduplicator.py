from urllib.parse import urlparse

class Deduplicator:

    def deduplicate(self, results):

        seen = set()
        unique = []

        for result in results:

            parsed = urlparse(result.url)

            normalized = (
                parsed.netloc +
                parsed.path.rstrip("/")
            )

            if normalized in seen:
                continue

            seen.add(normalized)
            unique.append(result)

        return unique