# SEARCH SKILL

You have been routed here because this task requires live/external information.

## MANDATORY BEHAVIOR
- Use web_search BEFORE answering. Never answer from memory when search was triggered.
- If the first result is insufficient, search again with refined terms.
- Answer naturally using the result — do not dump raw search output.

## AVAILABLE TOOLS
- `web_search` → `{ "query": string, "mode": "normal" | "deep", "max_results": int }`

| param        | default    | when to change                                         |
|------------- |------------|--------------------------------------------------------|
| `query`      | —          | always required; keep it 2–5 words                     |
| `mode`       | `"normal"` | use `"deep"` when you need full page content, not just a snippet |
| `max_results`| `5`        | increase to `8–10` only for comparison / survey tasks  |

## WHEN TO USE EACH MODE

**normal** (fast, ~2–4s)
- Factual lookups, quick definitions, recent news headlines
- You only need the title + snippet to answer

**deep** (thorough, ~15–30s)
- The snippet is too vague and you need full page content
- Comparing multiple sources in detail
- Technical documentation, step-by-step guides, prices, specs

## WORKFLOW
1. `web_search` with a tight 2–5 word query, `mode: "normal"` first
2. If results are thin or snippets don't contain enough detail → re-search with `mode: "deep"`
3. If a completely different angle is needed → re-search with rephrased query
4. `done: true` with answer synthesized from results — never paste raw tool output