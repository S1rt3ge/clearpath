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

router = APIRouter(prefix="/api/v1", tags=["analyze"])

# ---------------------------------------------------------------------------
# In-memory result cache: key → {"ts": float, "result": dict}
# ---------------------------------------------------------------------------
_result_cache: dict = {}
_CACHE_TTL = 300  # 5 minutes


def _cache_key(url: str, tenant_id: str, profile: dict) -> str:
    return (
        f"{tenant_id}:{url}"
        f":{profile.get('profile_type')}"
        f":{profile.get('reading_level')}"
        f":{profile.get('language', 'en')}"
    )


def _get_cached(key: str) -> Optional[dict]:
    entry = _result_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] < _CACHE_TTL:
        return entry["result"]
    del _result_cache[key]
    return None


def _set_cached(key: str, result: dict) -> None:
    _result_cache[key] = {"ts": time.time(), "result": result}


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


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_page(request: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    profile = await _load_or_create_profile(
        db, _parse_uuid(request.user_id), request.tenant_id
    )
    profile_dict = profile.to_dict()

    # Cache check
    key = _cache_key(request.url, request.tenant_id, profile_dict)
    cached = _get_cached(key)
    if cached:
        cached["from_cache"] = True
        return cached

    # Run agent graph
    graph = get_graph()
    state = await graph.ainvoke({
        "request": request.model_dump(),
        "user_profile": profile_dict,
        "page_analysis": None,
        "plan": None,
        "simplified_text": None,
        "transformations": None,
        "response": None,
        "error": None,
        "start_time": time.time(),
    })

    result = state["response"]

    # Store in cache and update interaction history
    _set_cached(key, result)
    profile.interaction_history = (profile.interaction_history or [])[-49:] + [{
        "url": request.url,
        "content_type": result.get("content_type") if result else None,
        "timestamp": time.time(),
    }]
    await db.commit()

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
            request_data = json.loads(data)
            request = AnalyzeRequest(**request_data)

            ws_uuid = _parse_uuid(request.user_id)
            profile = await _load_or_create_profile(db, ws_uuid, request.tenant_id)
            profile_dict = profile.to_dict()

            # Cache check — send instant response
            key = _cache_key(request.url, request.tenant_id, profile_dict)
            cached = _get_cached(key)
            if cached:
                await websocket.send_json({"status": "processing", "step": "cache"})
                await websocket.send_json({"status": "done", "result": cached})
                continue

            await websocket.send_json({"status": "processing", "step": "analyzer"})

            graph = get_graph()

            async for event in graph.astream({
                "request": request.model_dump(),
                "user_profile": profile_dict,
                "page_analysis": None,
                "plan": None,
                "simplified_text": None,
                "transformations": None,
                "response": None,
                "error": None,
                "start_time": time.time(),
            }):
                node_name = list(event.keys())[0]
                await websocket.send_json({"status": "processing", "step": node_name})

            result = event[node_name].get("response")
            if result:
                _set_cached(key, result)

            await websocket.send_json({"status": "done", "result": result})

    except WebSocketDisconnect:
        pass
