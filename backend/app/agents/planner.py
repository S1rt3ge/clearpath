"""
Planner Agent — Gemma 4 E4B via Ollama (local, private)
Decides which transformations to apply based on user cognitive profile
"""
import httpx
import json
from app.config import settings


async def plan_transformations(
    page_analysis: dict,
    user_profile: dict,
) -> dict:
    """
    Local model — user's cognitive data never leaves the machine.
    Returns a plan: list of actions to take.
    """

    profile_type = user_profile.get("profile_type", "low_literacy")
    reading_level = user_profile.get("reading_level", "B1")
    unknown_terms = user_profile.get("unknown_terms", [])
    content_type = page_analysis.get("content_type", "unknown")

    system_prompt = f"""You are a cognitive accessibility planner.
User profile: {profile_type}, reading level: {reading_level}
Previously unknown terms for this user: {unknown_terms[:10]}

Based on page analysis, decide what transformations to apply.
Return ONLY valid JSON:
{{
  "actions": ["simplify_text", "hide_distractions", "add_step_guide", "apply_dyslexia_font", "add_context_tips"],
  "agent_message": "Short friendly message to user about what you did (max 2 sentences)",
  "priority": "high|medium|low",
  "generate_steps": true/false,
  "generate_summary": true/false
}}"""

    user_prompt = f"""Page type: {content_type}
Complexity: {page_analysis.get('complexity_score', 5)}/10
Key elements: {page_analysis.get('key_elements', [])}
Action required: {page_analysis.get('action_required', 'read')}"""

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.gemma_local_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 256}
            }
        )

        result = response.json()
        content = result.get("message", {}).get("content", "")
        # Gemma 4 places the real response AFTER <channel|> when thinking is disabled
        if "<channel|>" in content:
            content = content.split("<channel|>", 1)[1]
        content = content.strip()
        # Strip markdown code fences the model sometimes wraps JSON in
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content
            content = content.rstrip("`").strip()

        try:
            if not content:
                raise json.JSONDecodeError("empty", "", 0)
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "actions": ["simplify_text"],
                "agent_message": "I've simplified this page for you.",
                "priority": "medium",
                "generate_steps": False,
                "generate_summary": True
            }
