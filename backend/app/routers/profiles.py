from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid


def _parse_uuid(value: str):
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None

from app.database import get_db
from app.models.user_profile import UserProfile

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


class ProfileCreate(BaseModel):
    tenant_id: str
    profile_type: str  # adhd | dyslexia | low_literacy
    reading_level: str = "B1"
    language: str = "en"


class ProfileUpdate(BaseModel):
    profile_type: Optional[str] = None
    reading_level: Optional[str] = None
    language: Optional[str] = None
    adhd_mode: Optional[bool] = None
    dyslexia_mode: Optional[bool] = None
    low_literacy_mode: Optional[bool] = None
    font_preference: Optional[str] = None
    reduce_distractions: Optional[bool] = None


@router.post("/")
async def create_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    profile = UserProfile(
        tenant_id=data.tenant_id,
        profile_type=data.profile_type,
        reading_level=data.reading_level,
        language=data.language,
        adhd_mode=data.profile_type == "adhd",
        dyslexia_mode=data.profile_type == "dyslexia",
        low_literacy_mode=data.profile_type == "low_literacy",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile.to_dict()


@router.get("/{profile_id}")
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    parsed = _parse_uuid(profile_id)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid profile ID format")
    result = await db.execute(select(UserProfile).where(UserProfile.id == parsed))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile.to_dict()


@router.patch("/{profile_id}")
async def update_profile(profile_id: str, data: ProfileUpdate, db: AsyncSession = Depends(get_db)):
    parsed = _parse_uuid(profile_id)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid profile ID format")
    result = await db.execute(select(UserProfile).where(UserProfile.id == parsed))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return profile.to_dict()


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

@router.get("/{profile_id}/history")
async def get_profile_history(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recent interaction history and hard terms for a profile.
    Used by the Chrome Extension popup to show "last visited X days ago".
    """
    parsed = _parse_uuid(profile_id)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid profile ID format")
    result = await db.execute(select(UserProfile).where(UserProfile.id == parsed))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    history = profile.interaction_history or []
    hard_terms = profile.unknown_terms or []
    top_domains = _count_domains(history)

    return {
        "profile_id": profile_id,
        "recent": history[-20:],
        "total_visits": len(history),
        "hard_terms": hard_terms[:20],
        "top_domains": top_domains,
        "error_patterns": profile.error_patterns or {},
    }


def _count_domains(history: list) -> list:
    from collections import Counter
    domains = []
    for entry in history:
        url = entry.get("url", "")
        if "://" in url:
            try:
                domain = url.split("://")[1].split("/")[0].replace("www.", "")
                domains.append(domain)
            except Exception:
                pass
    counts = Counter(domains).most_common(5)
    return [{"domain": d, "visits": c} for d, c in counts]


# ---------------------------------------------------------------------------
# Error reporting endpoint
# ---------------------------------------------------------------------------

class ErrorReport(BaseModel):
    topic: str
    url: str


@router.post("/{profile_id}/error")
async def report_error(
    profile_id: str,
    data: ErrorReport,
    db: AsyncSession = Depends(get_db),
):
    """
    Records a topic where the user made an error.
    Used by the Chrome Extension when user answers a test question wrong.
    Planner reads error_patterns to personalize agent_message.

    Example: POST /api/v1/profiles/{id}/error
    Body: {"topic": "recursion", "url": "https://moodle.example.com/quiz/1"}
    """
    parsed = _parse_uuid(profile_id)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid profile ID format")
    result = await db.execute(select(UserProfile).where(UserProfile.id == parsed))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    patterns = dict(profile.error_patterns or {})
    patterns[data.topic] = patterns.get(data.topic, 0) + 1

    if len(patterns) > 50:
        min_topic = min(patterns, key=patterns.get)
        del patterns[min_topic]

    profile.error_patterns = patterns
    await db.commit()

    return {
        "ok": True,
        "topic": data.topic,
        "count": patterns[data.topic],
        "all_patterns": dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True)),
    }
