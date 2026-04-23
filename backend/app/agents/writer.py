"""
Writer Agent — Gemma 4 E2B (fine-tuned) via Ollama (local)
Generates simplified Easy Language text.

Gemma 4 with think:false outputs reasoning then <channel|> then the clean answer.
num_predict=480 gives ~350 tokens for thinking + ~130 for the simplified text.
At normal GPU throughput (50 tok/s) this completes in ~10s when run in parallel
with the planner.  _strip_thinking() handles the edge-case where token budget
runs out before <channel|> is reached.
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


def _strip_thinking(content: str) -> str:
    """Extract the clean answer after <channel|>, with fallbacks."""
    # Primary: everything after the channel separator
    if "<channel|>" in content:
        answer = content.split("<channel|>", 1)[1].strip()
        if answer:
            return answer

    # Fallback 1: lines annotated (OK) in the thinking draft section
    ok_items = re.findall(r'\*+\s+(.+?)\s+\(OK\)', content)
    if ok_items:
        return "\n".join(s.strip() for s in ok_items)

    # Fallback 2: pull draft sentences from "Process Sentence N" blocks
    # Pattern: "Final Check: <sentence> (<word count> words)"
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
    return "\n".join(plain) if plain else content.strip()


async def simplify_text(
    text: str,
    reading_level: str = "A2",
    language: str = "en",
    max_sentences: int = 10,
) -> str:
    system_prompt = (
        f"Easy Language writer. Level {reading_level}. Language: {language}. "
        f"Rules: max 10 words per sentence, simple common words, one idea, active voice. "
        f"Output ONLY the simplified sentences, nothing else."
    )
    user_prompt = f"Simplify into max {max_sentences} sentences:\n\n{text[:1000]}"

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
                "options": {"temperature": 0.3, "num_predict": 480},
            },
        )
        content = response.json().get("message", {}).get("content", "")
        return _strip_thinking(content)
