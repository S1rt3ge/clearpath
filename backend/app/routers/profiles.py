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


def _count_domains(history: list) -> list:
    """Count recent visits by domain for the popup history view."""
    from collections import Counter
    from urllib.parse import urlparse

    domains = []
    for entry in history:
        try:
            domain = urlparse(entry.get("url", "")).netloc.replace("www.", "")
        except Exception:
            domain = ""
        if domain:
            domains.append(domain)

    return [
        {"domain": domain, "visits": visits}
        for domain, visits in Counter(domains).most_common(5)
    ]


@router.get("/{profile_id}/history")
async def get_profile_history(profile_id: str, db: AsyncSession = Depends(get_db)):
    parsed = _parse_uuid(profile_id)
    if not parsed:
        raise HTTPException(status_code=422, detail="Invalid profile ID format")

    result = await db.execute(select(UserProfile).where(UserProfile.id == parsed))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    history = profile.interaction_history or []
    return {
        "profile_id": profile_id,
        "recent": history[-20:],
        "total_visits": len(history),
        "hard_terms": (profile.unknown_terms or [])[:20],
        "top_domains": _count_domains(history),
        "error_patterns": profile.error_patterns or {},
    }


class ErrorReport(BaseModel):
    topic: str
    url: str


@router.post("/{profile_id}/error")
async def report_error(
    profile_id: str,
    data: ErrorReport,
    db: AsyncSession = Depends(get_db),
):
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
        "all_patterns": dict(
            sorted(patterns.items(), key=lambda item: item[1], reverse=True)
        ),
    }
