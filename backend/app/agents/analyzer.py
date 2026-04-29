"""
Analyzer Agent — Gemma 4 26B via Google AI Studio (multimodal)
Analyzes screenshot + DOM to determine content type and structure.
"""
import httpx
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse
from app.config import settings

logger = logging.getLogger("clearpath")


def _fallback_analysis(url: str, dom_text: str) -> dict:
    form_fields = _extract_form_fields_from_text(dom_text)
    content_type = _infer_content_type(url, dom_text, form_fields)
    action_required = {
        "form": "fill_form",
        "test": "take_test",
        "article": "read",
        "dashboard": "navigate",
    }.get(content_type, "read")

    return {
        "content_type": content_type,
        "complexity_score": 5,
        "key_elements": _fallback_key_elements(content_type, form_fields),
        "main_text_blocks": [dom_text[:500]] if dom_text and content_type != "form" else [],
        "distracting_elements": _fallback_distracting_elements(dom_text),
        "action_required": action_required,
        "form_fields": form_fields if content_type == "form" else [],
        "url": url,
    }


def _infer_content_type(url: str, dom_text: str, form_fields: list[dict]) -> str:
    lowered = f"{url} {dom_text}".lower()
    path = urlparse(url).path.lower()

    if form_fields or any(word in lowered for word in (" form", "submit", "email", "telephone")):
        if "quiz" not in lowered and "test" not in lowered:
            return "form"
    if any(word in lowered for word in ("quiz", "test", "exam", "question", "moodle")):
        return "test"
    if any(word in lowered for word in ("dashboard", "analytics", "overview", "metrics")):
        return "dashboard"
    if "wiki" in lowered or len(dom_text) > 800 or path.count("/") <= 2:
        return "article"
    return "unknown"


def _fallback_key_elements(content_type: str, form_fields: list[dict]) -> list[str]:
    if content_type == "form":
        return [field["label"] for field in form_fields] or ["form fields", "submit button"]
    if content_type == "test":
        return ["questions", "answers", "submit button"]
    if content_type == "article":
        return ["main article text"]
    return []


def _fallback_distracting_elements(dom_text: str) -> list[str]:
    lowered = dom_text.lower()
    selectors = []
    if "advertisement" in lowered or "sponsored" in lowered:
        selectors.extend([".advertisement", "[class*='ad']", "[id*='ad']"])
    if "newsletter" in lowered:
        selectors.append(".newsletter-signup")
    if "cookie" in lowered:
        selectors.append(".cookie-notice")
    return selectors


def _extract_form_fields_from_text(dom_text: str) -> list[dict]:
    fields = []
    for line in dom_text.splitlines():
        if not line.startswith("FORM_FIELD "):
            continue
        field = _parse_form_field_line(line)
        if field:
            fields.append(field)

    if fields:
        return fields[:20]

    lowered = dom_text.lower()
    common_fields = [
        ("customer name", "input[name='custname']", "Customer name", "Write your full name."),
        ("name", "input[name='name']", "Name", "Write your name."),
        ("email", "input[type='email'], input[name*='email']", "Email", "Write your email address."),
        ("telephone", "input[type='tel'], input[name*='phone'], input[name*='tel']", "Telephone", "Write your phone number."),
        ("delivery", "input[name*='delivery'], select[name*='delivery']", "Delivery", "Choose when you want delivery."),
        ("comments", "textarea, textarea[name*='comment']", "Comments", "Write any extra notes."),
    ]
    for needle, selector, label, hint in common_fields:
        if needle in lowered:
            fields.append({
                "selector": selector,
                "label": label,
                "hint": hint,
                "required": False,
            })
    return fields[:10]


def _parse_form_field_line(line: str) -> Optional[dict]:
    values = dict(re.findall(r'(\w+)="([^"]*)"', line))
    selector = values.get("selector")
    label = values.get("label") or values.get("name") or "Form field"
    if not selector:
        return None
    return {
        "selector": selector,
        "label": label,
        "hint": values.get("hint") or _hint_for_label(label),
        "required": values.get("required", "false").lower() == "true",
    }


def _hint_for_label(label: str) -> str:
    lowered = label.lower()
    if "email" in lowered:
        return "Write your email address."
    if "phone" in lowered or "telephone" in lowered:
        return "Write your phone number."
    if "name" in lowered:
        return "Write your name."
    if "comment" in lowered:
        return "Write any extra notes."
    return f"Enter {label.lower()}."


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
            logger.warning(
                f"Analyzer cloud error {response.status_code}; using local fallback"
            )
            return _fallback_analysis(url, dom_text)

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
