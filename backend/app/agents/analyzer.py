"""
Analyzer Agent — Gemma 4 26B via Google AI Studio (multimodal)
Analyzes screenshot + DOM to determine content type and structure.
"""
import httpx
import json
from typing import Optional
from app.config import settings


async def analyze_page(
    url: str,
    dom_text: str,
    screenshot_base64: Optional[str] = None
) -> dict:
    """
    Calls Gemma 4 26B (cloud, multimodal) to analyze the page.
    Returns structured JSON with content_type and key_elements.
    """

    system_prompt = """You are a web page analyzer for an accessibility tool.
Analyze the provided page content and return ONLY valid JSON with this structure:
{
  "content_type": "article|test|form|dashboard|unknown",
  "complexity_score": 1-10,
  "key_elements": ["list of important UI elements found"],
  "main_text_blocks": ["list of main text content blocks"],
  "distracting_elements": ["banners", "ads", "sidebars to hide"],
  "action_required": "read|fill_form|take_test|navigate"
}
No explanation, only JSON."""

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
                "max_tokens": 512,
                "temperature": 0.1,
            }
        )

        if not response.is_success:
            raise ValueError(f"Google AI Studio API error {response.status_code}: {response.text[:200]}")

        result = response.json()
        if not isinstance(result, dict) or "choices" not in result:
            raise ValueError(f"Unexpected response format: {str(result)[:200]}")

        content = result["choices"][0]["message"]["content"]

        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            return {
                "content_type": "unknown",
                "complexity_score": 5,
                "key_elements": [],
                "main_text_blocks": [dom_text[:500]],
                "distracting_elements": [],
                "action_required": "read"
            }
