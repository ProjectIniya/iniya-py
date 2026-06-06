"""
searchClient.py
--------------
A drop-in async mixin that adds multi-mode search capability to any class.

Modes
-----
SearchMode.NORMAL
    Fast path. Runs search providers in parallel, deduplicates, cleans,
    and sorts by provider relevance score. No web extraction, no authority
    check. Typical latency: 2-4s.

SearchMode.DEEP
    Full pipeline. Runs search → parallel web extraction + authority scoring
    → ranking by weighted final score. Use when result quality matters more
    than speed. Typical latency: 15-35s depending on network.

AI flag
-------
Both modes accept ai=True. When enabled, the top 5 ranked results are
passed to llm_summarize() and a summary string is included in the response.
Requires llm_summarize to be set in configure_search().

Progress callbacks
------------------
Pass an async callable to on_progress to receive live status strings as
the pipeline runs. Useful for streaming updates to a frontend.

    async def push(msg):
        await websocket.send(msg)

    await client.search("query", on_progress=push)


    client = MyClient()
    result = await client.search("query", mode=SearchMode.DEEP, ai=True)
    print(result["summary"])
    for r in result["results"]:
        print(r.title, r.final_score)

Return value
------------
search() returns a plain dict:
    {
        "query":   str,
        "mode":    "normal" | "deep",
        "ai":      bool,
        "results": List[SearchResult],   # sorted by final_score desc
        "summary": str | None,           # None if ai=False
        "elapsed": float,                # total seconds
    }

LLM contract
------------
llm_summarize must have this signature:
    def summarize(query: str, context: str) -> str

context is a pre-built string of the top 5 results — titles, URLs, and
truncated extracted content. The function is called in a thread via
asyncio.to_thread so blocking LLM clients (ollama, openai) work as-is.

Authority engine
----------------
The AuthorityEngine loads ~1M domain rankings from CSV on first use.
This takes ~5s and is done lazily in a background thread on the first
DEEP search. Subsequent calls reuse the loaded engine (instance-level
cache with asyncio.Lock to prevent double-loading).
"""

import asyncio
import re
import time
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable

from AI_Model.tools.search.orchestrator.search_manager import SearchManager
from AI_Model.tools.search.orchestrator.ranker import Ranker
from AI_Model.tools.search.extractors.extractor import Extractor
from AI_Model.tools.search.providers.tavily import TavilyProvider
from AI_Model.tools.search.providers.duckduckgo import DuckDuckGoProvider
from AI_Model.tools.search.authorityChecker.engine import AuthorityEngine


class SearchMode(Enum):
    """
    NORMAL — fast, relevance-sorted, no extraction or authority check.
    DEEP   — full pipeline with web extraction, authority scoring, and ranking.
    """
    NORMAL = "normal"
    DEEP   = "deep"


# Type alias for the optional progress callback.
# Must be an async callable that accepts a single status string.
ProgressCallback = Callable[[str], Awaitable[None]]


class SearchClient:
    """
    Mixin that adds search() to any async class.

    Requires configure_search() to be called before the first search.
    All state is stored on the instance with a '_' prefix to avoid
    collisions with the host class.
    """

    _authority_engine: Optional[AuthorityEngine] = None
    _authority_lock:   Optional[asyncio.Lock]    = None

    def __init__(
        self,
        tavily_key:         Optional[str]      = None,
        llm_summarize:      Optional[Callable] = None,
        max_results:        int                = 5,
        enrich_concurrency: int                = 4,
        authority_timeout:  int                = 20,
        extract_chars:      int                = 10000,
        llm_context_chars:  int                = 1500,
    ):
        self._tavily_key         = tavily_key
        self._llm_summarize      = llm_summarize
        self._max_results        = max_results
        self._enrich_concurrency = enrich_concurrency
        self._authority_timeout  = authority_timeout
        self._extract_chars      = extract_chars
        self._llm_context_chars  = llm_context_chars
        self._authority_lock     = asyncio.Lock()


    async def search(
        self,
        query:       str,
        mode:        SearchMode                 = SearchMode.NORMAL,
        ai:          bool                       = False,
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict:
        """
        Run a search and return structured results.

        Parameters
        ----------
        query : str
            The search query.

        mode : SearchMode | str
            NORMAL for fast results, DEEP for quality-ranked results.
            Accepts both the enum and plain strings ("normal", "deep").

        ai : bool
            If True, passes the top 5 results to llm_summarize and
            includes the output in response["summary"].

        on_progress : async callable, optional
            Called with a status string at each pipeline stage.
            Signature: async def callback(msg: str) -> None

        Returns
        -------
        dict with keys:
            query, mode, ai, results, summary, elapsed

        Raises
        ------
        RuntimeError
            If configure_search() has not been called, or if ai=True
            but no llm_summarize was provided.
        """
        if not hasattr(self, "_tavily_key"):
            raise RuntimeError("Call configure_search() before searching.")

        # accept plain strings as well as enum members
        if isinstance(mode, str):
            mode = SearchMode(mode.lower())

        t_start = time.perf_counter()

        async def progress(msg: str):
            if on_progress:
                await on_progress(msg)

        # build provider list based on what keys are available
        providers = []
        if self._tavily_key:
            providers.append(TavilyProvider(api_key=self._tavily_key))
        providers.append(DuckDuckGoProvider())

        await progress("searching...")
        manager = SearchManager(providers)
        raw     = await manager.search(query, max_results=self._max_results)
        await progress(f"found {len(raw)} results")

        if mode == SearchMode.NORMAL:
            results = self._rank_normal(raw)
        else:
            results = await self._run_deep(raw, progress)

        # always trim to max_results
        results = results[:self._max_results]

        summary = None
        if ai:
            if not self._llm_summarize:
                raise RuntimeError(
                    "Pass llm_summarize= to configure_search() to use ai=True."
                )
            await progress("summarizing...")
            context = self._build_context(results[:5])
            # run in thread — llm clients are typically synchronous/blocking
            summary = await asyncio.to_thread(self._llm_summarize, query, context)

        return {
            "query":   query,
            "mode":    mode.value,
            "ai":      ai,
            "results": results,
            "summary": summary,
            "elapsed": round(time.perf_counter() - t_start, 2),
        }

    # ------------------------------------------------------------------
    # Private pipeline methods
    # ------------------------------------------------------------------

    def _rank_normal(self, raw: list) -> list:
        """
        Fast ranking — no network calls.
        Sets final_score = provider relevance score (Tavily gives this;
        DuckDuckGo results default to 0.5 since they carry no score).
        Also parses freshness from snippet so at least that signal is live.
        """
        for r in raw:
            r.freshness_score = self._parse_freshness(r.content)
            r.final_score = (r.score or 0.5) * 0.8 + r.freshness_score * 0.2
        return sorted(raw, key=lambda r: r.final_score, reverse=True)

    async def _run_deep(self, raw: list, progress) -> list:
        """
        Full enrichment pipeline.

        For each result, runs web extraction and authority scoring in
        parallel (both within a result, and across results up to
        enrich_concurrency). Results are then passed to the Ranker which
        computes final_score from authority, quality, freshness, and
        relevance weights.
        """
        extractor        = Extractor()
        authority_engine = await self._get_authority_engine()
        sem              = asyncio.Semaphore(self._enrich_concurrency)

        async def enrich(r):
            async with sem:
                extracted, authority = await asyncio.gather(
                    extractor.extract(r.url),
                    authority_engine.analyze(r.url),
                    return_exceptions=True,
                )

                # extraction result
                r.extracted_content = (
                    extracted[:self._extract_chars]
                    if isinstance(extracted, str) else ""
                )

                # authority result — dict on success, Exception on failure
                if isinstance(authority, dict):
                    r.authority_score = authority["authority_score"]

                    # map individual provider signals back to result fields
                    for signal in authority.get("signals", []):
                        if signal.get("provider") == "spamhaus":
                            # spamhaus score=0.0 means LISTED (spam), score=0.5 means clean
                            # invert so spam_score=1.0 means definitely spam
                            raw_spam = signal.get("score", 0.5)
                            r.spam_score = round(1.0 - (raw_spam * 2), 3) if raw_spam < 0.5 else 0.0
                            break
                else:
                    r.authority_score = 0.0

                # freshness from snippet (extracted content may have better dates)
                text_for_freshness = r.extracted_content or r.content
                r.freshness_score = self._parse_freshness(text_for_freshness)

                await progress(
                    f"{'ok' if r.extracted_content else 'no content'} | "
                    f"auth={r.authority_score:.2f} | "
                    f"fresh={r.freshness_score:.2f} | "
                    f"spam={r.spam_score:.2f} | {r.url}"
                )

        await asyncio.gather(*[enrich(r) for r in raw])

        return Ranker().rank(raw)

    async def _get_authority_engine(self) -> AuthorityEngine:
        """
        Lazy-loads AuthorityEngine on first DEEP search.

        Loading reads ~1M CSV rows which takes ~5s and must not block
        the event loop — runs in a thread via asyncio.to_thread.
        asyncio.Lock ensures concurrent calls don't trigger double-loading.
        The loaded engine is cached at the instance level for all
        subsequent searches.
        """
        if self._authority_engine is not None:
            return self._authority_engine

        async with self._authority_lock:
            # re-check inside the lock (another coroutine may have loaded
            # it while we were waiting to acquire)
            if self._authority_engine is None:
                self._authority_engine = await asyncio.to_thread(AuthorityEngine)

        return self._authority_engine

    def _build_context(self, results: list) -> str:
        """
        Builds a plain-text context string from the top N results
        to pass to the LLM. Uses extracted_content when available,
        falls back to the search snippet.
        """
        return "\n\n".join([
            f"Source: {r.title}\nURL: {r.url}\n"
            f"{(r.extracted_content or r.content)[:self._llm_context_chars]}"
            for r in results
        ])

    # ------------------------------------------------------------------
    # Freshness helpers
    # ------------------------------------------------------------------

    # relative: "15 hours ago", "2 days ago", "3 weeks ago"
    _RE_RELATIVE = re.compile(
        r'(\d+)\s+(minute|hour|day|week|month)s?\s+ago',
        re.IGNORECASE,
    )

    # absolute: "March 10, 2026" / "Mar 10, 2026" / "2026-03-10"
    _RE_ABS_MDY   = re.compile(r'\b([A-Za-z]+\s+\d{1,2},?\s+\d{4})\b')
    _RE_ABS_ISO   = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')

    _UNIT_TO_HOURS = {
        "minute": 1 / 60,
        "hour":   1.0,
        "day":    24.0,
        "week":   168.0,
        "month":  730.0,   # ~30.4 days
    }
    _YEAR_HOURS = 8_760.0  # 365 days

    def _parse_freshness(self, text: str) -> float:
        """
        Returns a 0.0–1.0 freshness score parsed from the snippet/content.

        Scoring curve (hours_old → score):
            0 h  → 1.00
           24 h  → 0.997
            7 d  → 0.981
           30 d  → 0.918
          180 d  → 0.520
          365 d  → 0.0

        Falls back to 0.0 if no date/age hint is found.
        """
        if not text:
            return 0.0

        # --- try relative age first ("15 hours ago") ---
        m = self._RE_RELATIVE.search(text)
        if m:
            n    = int(m.group(1))
            unit = m.group(2).lower()
            hours_old = n * self._UNIT_TO_HOURS.get(unit, 24.0)
            return self._hours_to_score(hours_old)

        # --- try absolute dates ---
        now = datetime.now()

        # "March 10, 2026" / "Mar 10 2026"
        m = self._RE_ABS_MDY.search(text)
        if m:
            raw = m.group(1).replace(",", "")
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    hours_old = (now - dt).total_seconds() / 3600
                    return self._hours_to_score(max(0.0, hours_old))
                except ValueError:
                    continue

        # "2026-03-10"
        m = self._RE_ABS_ISO.search(text)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%Y-%m-%d")
                hours_old = (now - dt).total_seconds() / 3600
                return self._hours_to_score(max(0.0, hours_old))
            except ValueError:
                pass

        return 0.0

    def _hours_to_score(self, hours_old: float) -> float:
        """Linear decay from 1.0 at 0 h to 0.0 at 1 year."""
        return round(max(0.0, 1.0 - (hours_old / self._YEAR_HOURS)), 4)