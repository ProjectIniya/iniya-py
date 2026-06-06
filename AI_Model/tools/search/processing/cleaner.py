# processing/cleaner.py
import re

SKIP_PATTERNS = [
    "cookie", "accept all", "enable javascript", "privacy policy",
    "terms of service", "all rights reserved", "subscribe to",
    "sign up", "log in", "click here", "read more", "see more",
    "advertisement", "sponsored", "share this", "follow us",
]

class Cleaner:

    def clean(self, text: str) -> str:
        if not text:
            return ""

        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        lines = text.splitlines()
        cleaned = []

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if len(line) < 15:
                continue

            lower = line.lower()
            if any(pat in lower for pat in SKIP_PATTERNS):
                continue

            # drop lines that are mostly non-alpha (nav menus, breadcrumbs)
            alpha_ratio = sum(c.isalpha() for c in line) / len(line)
            if alpha_ratio < 0.4:
                continue

            cleaned.append(line)

        return "\n".join(cleaned)[:15000]