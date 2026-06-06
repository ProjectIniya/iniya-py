import importlib.util
import sys
import re

# Symbols that have a natural spoken equivalent
_SYMBOL_MAP = {
    "→": "to", "←": "from", "↔": "to and from",
    "≈": "approximately", "≠": "not equal to",
    "≤": "less than or equal to", "≥": "greater than or equal to",
    "×": "times", "÷": "divided by", "±": "plus or minus",
    "∞": "infinity", "∑": "sum", "∏": "product",
    "√": "square root of", "∫": "integral",
    "°": " degrees", "′": " prime", "″": " double prime",
    "α":"alpha","β":"beta","γ":"gamma","δ":"delta","ε":"epsilon",
    "θ":"theta","λ":"lambda","μ":"mu","π":"pi","σ":"sigma","ω":"omega",
    "Δ":"delta","Σ":"sigma","Ω":"omega","Φ":"phi","Ψ":"psi",
    "•": ",", "·": ",",
    "–": "-", "—": "-",
    "\u00a0": " ",              # non-breaking space
}

_SUP = str.maketrans("0123456789+-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
                     "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖ𝑞ʳˢᵗᵘᵛʷˣʸᶻᴬᴮᶜᴰᴱᶠᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾꟴᴿˢᵀᵁᵛᵂˣʸᶻ")
_SUB = str.maketrans("0123456789",
                     "₀₁₂₃₄₅₆₇₈₉")

def _fix_scripts(text: str) -> str:
    """Convert leftover ^x / ^{...} and _x / _{...} after pylatexenc."""
    import re
    # ^{abc} → superscript
    def _sup_group(m):
        return "".join(c.translate(_SUP) if c in _SUP.__self__ else c for c in m.group(1))
    # avoid using __self__; just translate directly
    def _sup_g(m):
        return m.group(1).translate(_SUP)
    def _sub_g(m):
        return m.group(1).translate(_SUB)

    text = re.sub(r'\^\{([^}]+)\}', _sup_g, text)   # ^{abc}
    text = re.sub(r'\^(.)',          _sup_g, text)   # ^x
    text = re.sub(r'_\{([^}]+)\}',  _sub_g, text)   # _{abc}
    text = re.sub(r'_(.)',           _sub_g, text)   # _x
    return text

try:
    from pylatexenc.latex2text import LatexNodes2Text
    _ltx = LatexNodes2Text()
    def _math(m):
        try:
            result = _ltx.latex_to_text(m.group(1).strip())
            return _fix_scripts(result)   # ← clean up leftover ^ and _
        except Exception:
            return _fix_scripts(m.group(1))
except ImportError:
    def _math(m): return m.group(1)   # passthrough if not installed


def lazy_import(name):
    spec = importlib.util.find_spec(name)
    loader = importlib.util.LazyLoader(spec.loader)
    spec.loader = loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def strip_for_tts(text: str) -> str:
    """
    Convert text to a clean, naturally speakable string for TTS (e.g. Piper).

    Handles:
      - ANSI escape codes
      - LaTeX math  ($...$ / $$...$$)  → spoken form via pylatexenc, or dropped
      - Markdown: code fences, inline code, bold, italic, headers,
                  blockquotes, horizontal rules, links, images, lists
      - Unicode symbols  → spoken equivalents where sensible
      - Leftover punctuation / whitespace cleanup
    """

    # 1. ANSI escape codes
    text = re.sub(r'\x1b\[[0-9;]*[mABCDEFGHJKSTfnsulh]', '', text)

    # 2. LaTeX display math  $$...$$  (must come before inline)
    text = re.sub(r'\$\$(.*?)\$\$', _math, text, flags=re.DOTALL)

    # 3. LaTeX inline math  $...$
    text = re.sub(r'\$([^$\n]+?)\$', _math, text)

    # 4. Fenced code blocks  ```lang\n...\n```  → skip content, say "code block"
    text = re.sub(r'```[^\n]*\n.*?```', 'code block', text, flags=re.DOTALL)

    # 5. Inline code  `...`  → keep content (it's usually a short word/name)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # 6. Markdown bold / italic  (order matters: *** before ** before *)
    text = re.sub(r'\*{3}(.+?)\*{3}', r'\1', text)
    text = re.sub(r'_{3}(.+?)_{3}',   r'\1', text)
    text = re.sub(r'\*{2}(.+?)\*{2}', r'\1', text)
    text = re.sub(r'_{2}(.+?)_{2}',   r'\1', text)
    text = re.sub(r'\*(.+?)\*',       r'\1', text)
    text = re.sub(r'_(.+?)_',         r'\1', text)

    # 7. Markdown headers  # / ## / ###  → just the heading text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # 8. Blockquotes  > ...
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)

    # 9. Horizontal rules  --- / === / ***
    text = re.sub(r'^[\-\*=_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 10. Images  ![alt](url)  → alt text only
    text = re.sub(r'!\[([^\]]*)\]\([^\)]*\)', r'\1', text)

    # 11. Links  [text](url)  → text only
    text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', text)

    # 12. Bare URLs
    text = re.sub(r'https?://\S+', '', text)

    # 13. List markers  - / * / + / 1.
    text = re.sub(r'^\s*[-\*\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+',   '', text, flags=re.MULTILINE)

    # 14. HTML tags (just in case)
    text = re.sub(r'<[^>]+>', '', text)

    # 15. Unicode symbol → spoken word
    for sym, word in _SYMBOL_MAP.items():
        text = text.replace(sym, f' {word} ')

    # 16. Remaining non-ASCII that Piper can't speak (box-drawing, braille, etc.)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)

    # 17. Collapse whitespace / fix sentence spacing
    text = re.sub(r'[ \t]+', ' ', text)           # multiple spaces → one
    text = re.sub(r'\n{3,}', '\n\n', text)         # 3+ newlines → 2
    text = re.sub(r' ([,\.;:!?])', r'\1', text)    # space before punctuation

    return text.strip()