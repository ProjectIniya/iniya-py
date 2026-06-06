# orchestrator/ranker.py


class Ranker:

    # authority  — domain reputation (Umbrella, Tranco, WHOIS, SSL, DNS)
    # quality    — was content actually extracted + how much
    # relevance  — provider's own relevance score (Tavily only; DDG = 0)
    # freshness  — how recent the content is
    # spam       — penalty multiplier applied after weighted sum
    WEIGHTS = {
        "authority":  0.40,
        "quality":    0.25,
        "relevance":  0.15,
        "freshness":  0.20,
    }
    SPAM_PENALTY = 0.35   # subtracted as: spam_score * SPAM_PENALTY

    def rank(self, results: list) -> list:
        for r in results:
            r.quality_score = self._quality(r)

            raw_score = (
                self.WEIGHTS["authority"]  * r.authority_score  +
                self.WEIGHTS["quality"]    * r.quality_score    +
                self.WEIGHTS["relevance"]  * (r.score or 0.0)   +
                self.WEIGHTS["freshness"]  * r.freshness_score
            )

            # spam_score of 1.0 = confirmed spam → heavy penalty
            spam_deduction = r.spam_score * self.SPAM_PENALTY
            r.final_score = round(max(0.0, raw_score - spam_deduction), 4)

        return sorted(results, key=lambda r: r.final_score, reverse=True)

    def _quality(self, result) -> float:
        """
        0.0–1.0 based on how much content was extracted.
        0.6 from length (normalised to 3000 chars), 0.4 bonus if anything extracted.
        """
        score = 0.0
        content_len = len(result.extracted_content or "")
        score += min(content_len / 3000, 1.0) * 0.6
        if result.extracted_content:
            score += 0.4
        return round(score, 3)