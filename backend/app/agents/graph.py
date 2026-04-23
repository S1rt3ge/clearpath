"""
LangGraph Multi-Agent Graph
Orchestrates: Analyzer → (Planner ‖ Writer) → Action
Planner and Writer run in parallel — Writer does not depend on Planner output.
"""
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
import asyncio
import time
import logging

logger = logging.getLogger("clearpath")

from app.agents.analyzer import analyze_page
from app.agents.planner import plan_transformations
from app.agents.writer import simplify_text
from app.agents.action import generate_transformations


class GraphState(TypedDict):
    # Input
    request: dict
    user_profile: dict

    # Agent outputs
    page_analysis: Optional[dict]
    plan: Optional[dict]
    simplified_text: Optional[str]
    hard_terms: Optional[List[str]]     # words from original absent in simplified
    transformations: Optional[List[dict]]

    # Final output
    response: Optional[dict]
    error: Optional[str]
    start_time: float
    last_visit_info: Optional[dict]     # {"days_ago": int, "url": str} — set by router


_ANALYZER_FALLBACK = {
    "content_type": "unknown",
    "complexity_score": 5,
    "key_elements": [],
    "main_text_blocks": [],
    "distracting_elements": [],
    "action_required": "read",
}

_PLANNER_FALLBACK = {
    "actions": ["simplify_text"],
    "agent_message": "I've made this page easier to read.",
    "generate_steps": False,
    "generate_summary": True,
}


async def analyzer_node(state: GraphState) -> GraphState:
    """Node 1: Analyze page with cloud model (multimodal)."""
    try:
        req = state["request"]
        analysis = await analyze_page(
            url=req.get("url", ""),
            dom_text=req.get("dom_text", ""),
            screenshot_base64=req.get("screenshot_base64"),
        )
        logger.info(f"Analyzer OK: content_type={analysis.get('content_type')}")
        return {**state, "page_analysis": analysis}
    except Exception as e:
        logger.error(f"Analyzer FAILED: {e}")
        dom_text = state["request"].get("dom_text", "")
        fallback = {
            **_ANALYZER_FALLBACK,
            "main_text_blocks": [dom_text[:2000]] if dom_text else [],
        }
        return {**state, "page_analysis": fallback}


async def planner_and_writer_node(state: GraphState) -> GraphState:
    """
    Node 2: Planner and Writer run in parallel with asyncio.gather().
    Writer only needs page_analysis + user_profile — no dependency on Planner.
    """
    analysis = state["page_analysis"]
    profile = state["user_profile"]

    # Prepare text for writer before launching both tasks
    main_text = " ".join(analysis.get("main_text_blocks", []))[:5000]
    if not main_text:
        main_text = state["request"].get("dom_text", "")[:5000]

    t0 = time.time()

    plan_result, writer_result = await asyncio.gather(
        plan_transformations(page_analysis=analysis, user_profile=profile),
        simplify_text(
            text=main_text,
            reading_level=profile.get("reading_level", "A2"),
            language=profile.get("language", "en"),
        ),
        return_exceptions=True,
    )

    elapsed = round(time.time() - t0, 1)

    if isinstance(plan_result, Exception):
        logger.error(f"Planner FAILED ({elapsed}s): {plan_result}")
        plan = _PLANNER_FALLBACK
    else:
        plan = plan_result
        if not plan.get("actions"):
            plan = {**plan, "actions": _PLANNER_FALLBACK["actions"]}
        logger.info(f"Planner OK ({elapsed}s): actions={plan.get('actions')}")

    if isinstance(writer_result, Exception):
        logger.error(f"Writer FAILED ({elapsed}s): {writer_result}")
        simplified = None
        hard_terms: List[str] = []
    else:
        simplified, hard_terms = writer_result
        logger.info(
            f"Writer OK ({elapsed}s): {len(simplified or '')} chars, "
            f"{len(hard_terms)} hard_terms"
        )

    return {**state, "plan": plan, "simplified_text": simplified, "hard_terms": hard_terms}


async def action_node(state: GraphState) -> GraphState:
    """Node 3: Generate DOM transformation commands."""
    try:
        transformations = await generate_transformations(
            plan=state["plan"],
            simplified_text=state.get("simplified_text", ""),
            page_analysis=state["page_analysis"],
            user_profile=state["user_profile"],
        )

        elapsed_ms = int((time.time() - state["start_time"]) * 1000)
        response = {
            "content_type": state["page_analysis"].get("content_type", "unknown"),
            "transformations": [t.model_dump() for t in transformations],
            "agent_message": state["plan"].get("agent_message", "Page adapted for you."),
            "processing_time_ms": elapsed_ms,
            "hard_terms": state.get("hard_terms") or [],
            "last_visit_info": state.get("last_visit_info"),
        }

        logger.info(f"Action OK: {len(response['transformations'])} transforms, {elapsed_ms}ms total")
        return {**state, "transformations": response["transformations"], "response": response}
    except Exception as e:
        logger.error(f"Action FAILED: {e}")
        return {**state, "error": f"Action failed: {str(e)}"}


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("analyzer", analyzer_node)
    graph.add_node("planner_and_writer", planner_and_writer_node)
    graph.add_node("action", action_node)

    graph.set_entry_point("analyzer")
    graph.add_edge("analyzer", "planner_and_writer")
    graph.add_edge("planner_and_writer", "action")
    graph.add_edge("action", END)

    return graph.compile()


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
