"""
Writer Agent — Gemma 4 E2B (fine-tuned) via Ollama (local)
Generates simplified Easy Language text.

Gemma 4 with think:false outputs reasoning then <channel|> then the clean answer.

Pipeline:
  1. _clean_text()          — strip [1] citations and nav boilerplate
  2. _extract_article_text() — skip infobox fragments; keep real sentences only
  3. Ollama call             — num_predict=640 (≈480 thinking + 160 answer tokens)
  4. _strip_thinking()       — extract text after <channel|> with fallbacks
  5. Fallback                — if still empty, return first sentences of article_text

At ~14 tok/s (warm GPU, no VRAM competition) the call completes in ~40s when
serialised with the planner.  The 90s httpx timeout leaves ample headroom even
when another model briefly contends for VRAM.
"""
import re
import httpx
from app.config import settings

FINETUNED_MODEL = "clearpath-writer:latest"


async def _model_exists(client: httpx.AsyncClient, model_name: str) -> bool:
    try:
        r = await client.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        return model_name in [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return False


# Markers that identify the start of a raw thinking dump.
# If the model output begins with any of these, <channel|> was never reached
# (token budget ran out during the thinking phase).
_THINKING_MARKERS = (
    "Thinking Process:",
    "**Analyze the Request",
    "**Step 1",
    "Step 1.",
    "Let me analyze",
    "I need to simplify",
    "I will simplify",
    "**Analyze:",
)


def _strip_thinking(content: str) -> str:
    """Extract the clean answer after <channel|>, with fallbacks.

    Returns "" when only thinking content is present (token budget exhausted
    before <channel|> was written) — callers must handle the empty-string case.
    """
    # Primary: everything after the channel separator
    if "<channel|>" in content:
        answer = content.split("<channel|>", 1)[1].strip()
        if answer:
            return answer

    # Early exit: output starts with a known thinking marker → no clean answer
    stripped = content.strip()
    if any(stripped.startswith(m) for m in _THINKING_MARKERS):
        return ""

    # Fallback 1: lines annotated (OK) in the thinking draft section
    ok_items = re.findall(r'\*+\s+(.+?)\s+\(OK\)', content)
    if ok_items:
        return "\n".join(s.strip() for s in ok_items)

    # Fallback 2: pull draft sentences from "Final Check: <sentence> (<N> words)"
    finals = re.findall(r'Final Check:\s*(.+?)\s*\(\d+ words?\)', content)
    if len(finals) >= 2:
        return "\n".join(f.strip() for f in finals)

    # Fallback 3: plain capital-start, period-end sentences without markdown
    plain = [
        re.sub(r'^\*+\s*', '', l).strip()
        for l in content.splitlines()
        if re.match(r'^\*?\s*[A-ZА-Я]', l.strip())
        and l.strip().endswith('.')
        and len(l.strip()) < 120
        and '**' not in l
        and 'Thinking' not in l
        and 'Process' not in l
    ]
    # Return "" — never dump raw thinking content to the user
    return "\n".join(plain) if plain else ""


# ---------------------------------------------------------------------------
# Input cleaning
# ---------------------------------------------------------------------------

_NAV_RE = re.compile(
    r'Перейти к содержанию|'
    r'Материал из Википедии[^.]*\.?|'
    r'У этого термина существуют[^.]*\.?|'
    r'Jump to content|'
    r'From Wikipedia,?\s*the free encyclopedia|'
    r'Navigation menu|'
    r'This article is about',
    re.IGNORECASE,
)


def _clean_text(raw: str) -> str:
    """Strip citation noise and nav boilerplate.

    Works on both newline-separated and flat dom_text strings.
    """
    text = raw
    text = re.sub(r'\[\d+\]', '', text)                         # [1], [12]
    text = re.sub(r'\[citation needed\]', '', text, flags=re.IGNORECASE)
    text = _NAV_RE.sub(' ', text)                               # nav phrases
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def _extract_article_text(cleaned: str, max_chars: int = 800) -> str:
    """Skip infobox fragments, return only real article prose sentences.

    Infobox table entries (e.g. "Класс языка объектно-ориентированный") are
    short or don't end with sentence-ending punctuation.  Real sentences end
    with a period/!/? and are usually longer than 50 characters.
    """
    chunks = re.split(r'(?<=[.!?])\s+|\n+', cleaned)
    meaningful = [
        c.strip() for c in chunks
        if c.strip() and c.strip()[-1] in '.!?' and len(c.strip()) > 50
    ]
    if not meaningful:
        # Fallback: take the tail where article text usually lives
        return cleaned[-max_chars:].strip() if len(cleaned) > max_chars else cleaned
    return ' '.join(meaningful)[:max_chars]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def simplify_text(
    text: str,
    reading_level: str = "A2",
    language: str = "en",
    max_sentences: int = 10,
) -> str:
    cleaned = _clean_text(text)
    article_text = _extract_article_text(cleaned)

    system_prompt = (
        f"Easy Language writer. Level {reading_level}. Language: {language}. "
        f"Rules: max 10 words per sentence, simple common words, one idea, active voice. "
        f"Output ONLY the simplified sentences, nothing else."
    )
    user_prompt = f"Simplify into max {max_sentences} sentences:\n\n{article_text}"

    async with httpx.AsyncClient(timeout=90.0) as client:
        use_model = settings.gemma_local_model
        if await _model_exists(client, FINETUNED_MODEL):
            use_model = FINETUNED_MODEL

        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": use_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": False,
                "think": False,
                # 640 = ~480 thinking tokens + ~160 tokens for the answer.
                # At 14 tok/s (warm GPU)  → ~46s total
                # At 10 tok/s (slow GPU)  → ~64s total  (within 90s timeout)
                "options": {"temperature": 0.3, "num_predict": 640},
            },
        )
        content = response.json().get("message", {}).get("content", "")
        result = _strip_thinking(content)

        if not result:
            # Token budget exhausted before clean answer.
            # Return first few article sentences — no infobox noise, no thinking.
            sents = [
                s.strip() for s in re.split(r'(?<=[.!?])\s+', article_text)
                if len(s.strip()) > 25
            ]
            result = " ".join(sents[:4]) if sents else article_text[:300].strip()

        return result
