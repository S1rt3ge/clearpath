"""
Analyzer Agent — Gemma 4 26B via Google AI Studio (multimodal)
Analyzes screenshot + DOM to determine content type and structure.
"""
import httpx
import json
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("clearpath")


def _fallback_analysis(url: str, dom_text: str) -> dict:
    return {
        "content_type": "unknown",
        "complexity_score": 5,
        "key_elements": [],
        "main_text_blocks": [dom_text[:500]] if dom_text else [],
        "distracting_elements": [],
        "action_required": "read",
        "form_fields": [],
        "url": url,
    }


async def analyze_page(
    url: str,
    dom_text: str,
    screenshot_base64: Optional[str] = None
) -> dict:
    """
    Calls Gemma 4 26B (cloud, multimodal) to analyze the page.
    Returns structured JSON with content_type and key_elements.
    """

    system_prompt = """You are a web page analyzer for a cognitive accessibility tool.
Analyze the provided page content (URL, DOM text, optional screenshot).
Return ONLY valid JSON, no explanation, no markdown, just the JSON object.

Required structure:
{
  "content_type": "article|test|form|dashboard|unknown",
  "complexity_score": 1-10,
  "key_elements": ["list of important UI elements found on the page"],
  "main_text_blocks": ["up to 3 main text paragraphs, actual content only, no navigation"],
  "distracting_elements": ["CSS selectors of ads/banners/sidebars that should be hidden"],
  "action_required": "read|fill_form|take_test|navigate",
  "form_fields": [
    {
      "selector": "CSS selector pointing directly to the input/select/textarea element",
      "label": "Human-readable label text as shown on page",
      "hint": "Simple A2-level explanation of what to enter here, in the same language as the page",
      "required": true
    }
  ]
}

Rules:
- form_fields: populate ONLY when content_type is "form", otherwise return empty array []
- distracting_elements: include selectors like .advertisement, .banner, aside, [id*="ad"],
  [class*="promo"], [class*="popup"], .cookie-notice, .newsletter-signup
- main_text_blocks: real article sentences only, skip nav/footer/boilerplate
- complexity_score: 1=very simple (A1), 10=very complex (C2 academic)
- If content_type is "test": set action_required to "take_test"
- If content_type is "form": set action_required to "fill_form"
"""

    user_content = f"""URL: {url}

Page text content:
{dom_text[:3000]}"""

    # Build message content
    messages_content = []

    if screenshot_base64:
        messages_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{screenshot_base64}"
            }
        })

    messages_content.append({
        "type": "text",
        "text": user_content
    })

    # Call Google AI Studio (OpenAI-compatible endpoint)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.google_ai_studio_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.gemma_cloud_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": messages_content}
                ],
                "max_tokens": 768,
                "temperature": 0.1,
            }
        )

        if not response.is_success:
            raise ValueError(f"Google AI Studio API error {response.status_code}: {response.text[:200]}")

        result_json = response.json()
        if not isinstance(result_json, dict):
            logger.warning("Analyzer: unexpected response format")
            return _fallback_analysis(url, dom_text)

        choices = result_json.get("choices", [])
        if not choices:
            logger.warning("Analyzer: Google AI Studio returned no choices")
            return _fallback_analysis(url, dom_text)

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            logger.warning("Analyzer: Google AI Studio returned empty content")
            return _fallback_analysis(url, dom_text)

        content = content.strip()
        if content.startswith("```"):
            lines = [line for line in content.splitlines() if not line.startswith("```")]
            content = "\n".join(lines).strip()

        try:
            result = json.loads(content)
            result["url"] = url
            result.setdefault("form_fields", [])
            result.setdefault("distracting_elements", [])
            result.setdefault("main_text_blocks", [])
            if result.get("content_type") != "form":
                result["form_fields"] = []
            logger.debug(
                f"Analyzer: type={result.get('content_type')}, "
                f"complexity={result.get('complexity_score')}, "
                f"fields={len(result.get('form_fields', []))}"
            )
            return result
        except json.JSONDecodeError:
            logger.warning("Analyzer: JSON parse failed, using fallback")
            return _fallback_analysis(url, dom_text)
