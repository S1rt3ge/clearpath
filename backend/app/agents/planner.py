"""
Planner Agent — Gemma 4 E4B via Ollama (local, private)
Decides which transformations to apply based on user cognitive profile
"""
import httpx
import json
from urllib.parse import urlparse
from app.config import settings


def _strip_json_content(content: str) -> str:
    if "<channel|>" in content:
        content = content.split("<channel|>", 1)[1]
    content = content.strip()
    if content.startswith("```"):
        lines = [line for line in content.splitlines() if not line.startswith("```")]
        content = "\n".join(lines).strip()
    return content


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
    content_type = page_analysis.get("content_type", "unknown")
    current_url = page_analysis.get("url", "")

    visited_content = user_profile.get("visited_content", [])
    visited_urls = [entry.get("url", "") for entry in visited_content[-20:]]
    seen_before = bool(current_url and any(current_url in url for url in visited_urls))

    visited_domains = []
    for visited_url in visited_urls:
        try:
            domain = urlparse(visited_url).netloc.replace("www.", "")
        except Exception:
            domain = ""
        if domain and domain not in visited_domains:
            visited_domains.append(domain)
    visited_domains = visited_domains[:5]

    history_note = ""
    if seen_before:
        history_note = (
            "\nIMPORTANT: User has visited this page before. "
            "Set seen_before=true in response. Focus agent_message on new information only."
        )
    elif visited_domains:
        history_note = f"\nUser recently visited: {', '.join(visited_domains)}."

    error_patterns = user_profile.get("error_patterns", {})
    errors_note = ""
    if error_patterns and profile_type == "adhd":
        top_errors = sorted(error_patterns.items(), key=lambda item: item[1], reverse=True)[:3]
        errors_str = ", ".join(f'"{topic}"' for topic, _ in top_errors)
        errors_note = (
            f"\nUser previously struggled with: {errors_str}. "
            "If this is a test page, mention these topics in agent_message "
            "and set generate_steps=true."
        )

    system_prompt = f"""You are a cognitive accessibility planner.
User profile: {profile_type}, reading level: {reading_level}

Based on page analysis, decide what transformations to apply.
Return ONLY valid JSON:
{{
  "actions": ["simplify_text", "hide_distractions", "add_step_guide", "apply_dyslexia_font", "wizard_form"],
  "agent_message": "Short friendly message in the page language (max 2 sentences)",
  "priority": "high|medium|low",
  "generate_steps": true/false,
  "generate_summary": true/false,
  "seen_before": true/false
}}{history_note}{errors_note}"""

    user_prompt = f"""Page type: {content_type}
Complexity: {page_analysis.get('complexity_score', 5)}/10
Action required: {page_analysis.get('action_required', 'read')}"""

    async with httpx.AsyncClient(timeout=20.0) as client:
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
                "options": {"temperature": 0.05, "num_predict": 128}
            }
        )

        result = response.json()
        content = _strip_json_content(result.get("message", {}).get("content", ""))

        try:
            if not content:
                raise json.JSONDecodeError("empty", "", 0)
            plan = json.loads(content)
            if not isinstance(plan, dict):
                raise json.JSONDecodeError("object expected", content, 0)
        except json.JSONDecodeError:
            fallback_message = "I've made this page easier to read."
            if error_patterns and profile_type == "adhd":
                top_errors = sorted(error_patterns.items(), key=lambda item: item[1], reverse=True)
                if top_errors:
                    fallback_message = (
                        f"You previously struggled with {top_errors[0][0]}. "
                        "I prepared this page with extra focus support."
                    )
            plan = {
                "actions": ["simplify_text"],
                "agent_message": fallback_message,
                "priority": "medium",
                "generate_steps": profile_type == "adhd" and content_type == "test",
                "generate_summary": True,
                "seen_before": False,
            }

        raw_actions = plan.get("actions") or ["simplify_text"]
        actions = raw_actions if isinstance(raw_actions, list) else [str(raw_actions)]
        if content_type == "test" and profile_type == "adhd":
            plan["generate_steps"] = True
            if "add_step_guide" not in actions:
                actions.append("add_step_guide")
        if content_type == "form" and profile_type == "low_literacy":
            if "wizard_form" not in actions:
                actions.append("wizard_form")
        plan["actions"] = actions
        plan["seen_before"] = bool(plan.get("seen_before") or seen_before)
        plan.setdefault("priority", "medium")
        plan.setdefault("generate_steps", False)
        plan.setdefault("generate_summary", True)
        plan.setdefault("agent_message", "I've made this page easier to read.")
        return plan
