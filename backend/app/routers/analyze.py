import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import time
import uuid
from typing import Optional

from app.database import get_db
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.agents.graph import get_graph
from app.models.user_profile import UserProfile
from app.models.analysis_cache import AnalysisCache
from app.config import settings

logger = logging.getLogger("clearpath")

router = APIRouter(prefix="/api/v1", tags=["analyze"])

_CACHE_TTL_MINUTES = settings.cache_ttl_minutes


# ---------------------------------------------------------------------------
# PostgreSQL cache helpers (L1 = this process memory is gone; L2 = PG survives restart)
# ---------------------------------------------------------------------------

async def _db_get_cache(db: AsyncSession, key: str) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    row = await db.execute(
        select(AnalysisCache).where(
            AnalysisCache.cache_key == key,
            AnalysisCache.expires_at > now,
        )
    )
    entry = row.scalar_one_or_none()
    return entry.result if entry else None


async def _db_set_cache(db: AsyncSession, key: str, result: dict) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=_CACHE_TTL_MINUTES)
    existing = await db.execute(
        select(AnalysisCache).where(AnalysisCache.cache_key == key)
    )
    entry = existing.scalar_one_or_none()
    if entry:
        entry.result = result
        entry.expires_at = expires
    else:
        db.add(AnalysisCache(cache_key=key, result=result, expires_at=expires))
    await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_uuid(value: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


async def _load_or_create_profile(
    db: AsyncSession,
    user_uuid: Optional[uuid.UUID],
    tenant_id: str,
) -> UserProfile:
    if user_uuid:
        result = await db.execute(
            select(UserProfile).where(
                UserProfile.id == user_uuid,
                UserProfile.tenant_id == tenant_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile:
            return profile

    profile = UserProfile(
        tenant_id=tenant_id,
        profile_type="low_literacy",
        reading_level="A2",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


def _build_initial_state(request: AnalyzeRequest, profile_dict: dict) -> dict:
    """Construct the LangGraph initial state from a validated request."""
    return {
        "request": request.model_dump(),
        "user_profile": profile_dict,
        "page_analysis": None,
        "plan": None,
        "simplified_text": None,
        "hard_terms": None,
        "transformations": None,
        "response": None,
        "error": None,
        "start_time": time.time(),
        "last_visit_info": None,
    }


def _build_last_visit_info(profile: UserProfile, url: str) -> Optional[dict]:
    """Return visit metadata if user has been to this URL before."""
    history = profile.interaction_history or []
    last = next((h for h in reversed(history) if h.get("url") == url), None)
    if not last:
        return None
    days_ago = int((time.time() - last["timestamp"]) / 86400)
    return {"days_ago": days_ago, "url": url}


def _update_profile_after_analysis(
    profile: UserProfile,
    url: str,
    result: dict,
) -> None:
    """Persist hard_terms, visited_content and interaction_history to the profile object.

    Caller must still call db.commit() after this.
    """
    hard_terms = result.get("hard_terms") or []

    # Merge hard_terms into unknown_terms (union, capped at 100)
    existing_terms = set(profile.unknown_terms or [])
    profile.unknown_terms = list(existing_terms | set(hard_terms))[:100]

    # Track visited URLs for duplicate-visit detection
    profile.visited_content = (profile.visited_content or [])[-99:] + [
        {"url": url, "ts": time.time()}
    ]

    # Keep last 50 interaction records
    profile.interaction_history = (profile.interaction_history or [])[-49:] + [{
        "url": url,
        "content_type": result.get("content_type"),
        "timestamp": time.time(),
    }]


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_page(request: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    profile = await _load_or_create_profile(
        db, _parse_uuid(request.user_id), request.tenant_id
    )
    profile_dict = profile.to_dict()

    # --- PostgreSQL cache check ---
    cache_key = AnalysisCache.make_key(
        url=request.url,
        tenant_id=request.tenant_id,
        profile_type=profile_dict.get("profile_type", ""),
        reading_level=profile_dict.get("reading_level", ""),
        language=profile_dict.get("language", "en"),
    )
    cached = await _db_get_cache(db, cache_key)
    if cached:
        logger.info(f"Cache HIT: {request.url[:60]}")
        cached = dict(cached)
        cached["from_cache"] = True
        cached["last_visit_info"] = _build_last_visit_info(profile, request.url)
        _update_profile_after_analysis(profile, request.url, cached)
        await db.commit()
        return cached

    # --- Build initial state with last_visit_info ---
    initial_state = _build_initial_state(request, profile_dict)
    initial_state["last_visit_info"] = _build_last_visit_info(profile, request.url)

    # --- Run agent graph ---
    graph = get_graph()
    state = await graph.ainvoke(initial_state)
    result = state["response"]

    if result:
        await _db_set_cache(db, cache_key, result)
        _update_profile_after_analysis(profile, request.url, result)
        await db.commit()
        logger.info(
            f"Analysis complete: {result.get('processing_time_ms')}ms, "
            f"cache_key={cache_key[:12]}…"
        )

    return result


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/analyze")
async def analyze_websocket(websocket: WebSocket, db: AsyncSession = Depends(get_db)):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                request_data = json.loads(data)
                request = AnalyzeRequest(**request_data)
            except (json.JSONDecodeError, ValueError) as exc:
                await websocket.send_json({"status": "error", "message": str(exc)})
                continue

            ws_uuid = _parse_uuid(request.user_id)
            profile = await _load_or_create_profile(db, ws_uuid, request.tenant_id)
            profile_dict = profile.to_dict()

            # --- PostgreSQL cache check ---
            cache_key = AnalysisCache.make_key(
                url=request.url,
                tenant_id=request.tenant_id,
                profile_type=profile_dict.get("profile_type", ""),
                reading_level=profile_dict.get("reading_level", ""),
                language=profile_dict.get("language", "en"),
            )
            cached = await _db_get_cache(db, cache_key)
            if cached:
                await websocket.send_json({"status": "processing", "step": "cache"})
                cached = dict(cached)
                cached["from_cache"] = True
                cached["last_visit_info"] = _build_last_visit_info(profile, request.url)
                _update_profile_after_analysis(profile, request.url, cached)
                await db.commit()
                await websocket.send_json({"status": "done", "result": cached})
                continue

            await websocket.send_json({"status": "processing", "step": "analyzer"})

            # --- Build initial state with last_visit_info ---
            initial_state = _build_initial_state(request, profile_dict)
            initial_state["last_visit_info"] = _build_last_visit_info(profile, request.url)

            graph = get_graph()
            final_state: dict = {}

            try:
                async for event in graph.astream(initial_state):
                    node_name = next(iter(event))
                    final_state = event[node_name]
                    await websocket.send_json({"status": "processing", "step": node_name})
            except Exception as exc:
                logger.error(f"WebSocket graph error: {exc}")
                await websocket.send_json({"status": "error", "message": "Analysis failed"})
                continue

            result = final_state.get("response")
            if result:
                await _db_set_cache(db, cache_key, result)
                _update_profile_after_analysis(profile, request.url, result)
                await db.commit()

            await websocket.send_json({"status": "done", "result": result})

    except WebSocketDisconnect:
        pass
