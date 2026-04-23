"""
PostgreSQL-based analysis result cache.

Survives container restarts and is shared across all uvicorn workers.
TTL is enforced via the expires_at column — stale entries are purged
by the background cleanup task in main.py.

Cache key: SHA-256 of (tenant_id, url, profile_type, reading_level, language)
so that different user profiles on the same URL get different cached results,
and the URL is never stored in plain text.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key = Column(String(64), nullable=False, unique=True, index=True)
    result = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    @staticmethod
    def make_key(
        url: str,
        tenant_id: str,
        profile_type: str,
        reading_level: str,
        language: str,
    ) -> str:
        """Return SHA-256 hex digest of the cache dimensions."""
        raw = f"{tenant_id}:{url}:{profile_type}:{reading_level}:{language}"
        return hashlib.sha256(raw.encode()).hexdigest()
