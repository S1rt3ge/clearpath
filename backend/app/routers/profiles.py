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
