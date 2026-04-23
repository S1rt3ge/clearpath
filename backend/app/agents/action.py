"""
Action Agent — Gemma 4 E4B via Ollama (local)
Generates concrete DOM transformation instructions via function calling
"""
import httpx
import json
from typing import List
from app.config import settings
from app.schemas.analyze import DOMTransformation


async def generate_transformations(
    plan: dict,
    simplified_text: str,
    page_analysis: dict,
    user_profile: dict,
) -> List[DOMTransformation]:
    """
    Converts the plan into concrete DOM transformation instructions
    that the Chrome Extension will execute.
    """

    actions = plan.get("actions", [])
    profile_type = user_profile.get("profile_type", "low_literacy")
    transformations = []

    # Apply font for dyslexia
    if "apply_dyslexia_font" in actions or profile_type == "dyslexia":
        transformations.append(DOMTransformation(
            action="apply_font",
            selector="body",
            style={
                "fontFamily": "OpenDyslexic, Arial, sans-serif",
                "fontSize": "18px",
                "lineHeight": "1.8",
                "letterSpacing": "0.05em",
                "wordSpacing": "0.1em"
            }
        ))

    # Hide distracting elements for ADHD
    if "hide_distractions" in actions or profile_type == "adhd":
        for element in page_analysis.get("distracting_elements", []):
            transformations.append(DOMTransformation(
                action="hide_element",
                selector=element,
            ))

    # Add simplified text overlay
    if "simplify_text" in actions and simplified_text:
        transformations.append(DOMTransformation(
            action="simplify_text",
            selector="main, article, .content, #content",
            content=simplified_text
        ))

    # Add step guide for tests
    if plan.get("generate_steps") and page_analysis.get("content_type") == "test":
        steps_prompt = f"""Create a 5-step preparation guide for a student with {profile_type}
taking a test. Keep it simple and encouraging. Return as JSON array of strings."""

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.gemma_local_model,
                    "messages": [{"role": "user", "content": steps_prompt}],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.4, "num_predict": 256}
                }
            )
            content = response.json().get("message", {}).get("content", "")
            try:
                steps = json.loads(content.strip())
                transformations.append(DOMTransformation(
                    action="add_step_guide",
                    content=json.dumps(steps)
                ))
            except Exception:
                pass

    return transformations
