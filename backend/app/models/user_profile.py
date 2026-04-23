from sqlalchemy import Column, String, DateTime, JSON, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid
from app.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), nullable=False, index=True)  # multi-tenancy

    # Cognitive Profile
    profile_type = Column(String(50), nullable=False)  # adhd | dyslexia | low_literacy
    reading_level = Column(String(5), default="B1")    # A1 | A2 | B1 | B2 | C1 | C2
    language = Column(String(10), default="en")

    # Profile flags
    adhd_mode = Column(Boolean, default=False)
    dyslexia_mode = Column(Boolean, default=False)
    low_literacy_mode = Column(Boolean, default=False)

    # Preferences
    font_preference = Column(String(100), default="OpenDyslexic")
    font_size_multiplier = Column(Float, default=1.0)
    reduce_distractions = Column(Boolean, default=True)

    # Memory (Long-term)
    interaction_history = Column(JSON, default=list)   # list of interactions
    unknown_terms = Column(JSON, default=list)          # terms user struggled with
    error_patterns = Column(JSON, default=dict)         # per-site error patterns
    visited_content = Column(JSON, default=list)        # content already seen

    # Metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": str(self.id),
            "tenant_id": self.tenant_id,
            "profile_type": self.profile_type,
            "reading_level": self.reading_level,
            "language": self.language,
            "adhd_mode": self.adhd_mode,
            "dyslexia_mode": self.dyslexia_mode,
            "low_literacy_mode": self.low_literacy_mode,
            "font_preference": self.font_preference,
            "font_size_multiplier": self.font_size_multiplier,
            "reduce_distractions": self.reduce_distractions,
            "interaction_history": self.interaction_history or [],
            "unknown_terms": self.unknown_terms or [],
            "error_patterns": self.error_patterns or {},
            "visited_content": self.visited_content or [],
        }
