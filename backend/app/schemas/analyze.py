from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum


class ContentType(str, Enum):
    ARTICLE = "article"
    TEST = "test"
    FORM = "form"
    DASHBOARD = "dashboard"
    UNKNOWN = "unknown"


class ProfileType(str, Enum):
    ADHD = "adhd"
    DYSLEXIA = "dyslexia"
    LOW_LITERACY = "low_literacy"


class AnalyzeRequest(BaseModel):
    user_id: str
    tenant_id: str
    url: str
    page_title: str
    dom_text: str                          # plain text extracted from DOM
    screenshot_base64: Optional[str] = None  # base64 PNG for multimodal analysis


class DOMTransformation(BaseModel):
    action: str          # simplify_text | hide_element | add_guide | apply_font | add_step
    selector: Optional[str] = None
    content: Optional[str] = None
    style: Optional[Dict[str, str]] = None


class AnalyzeResponse(BaseModel):
    content_type: ContentType
    transformations: List[DOMTransformation]
    agent_message: str                     # What the agent "says" to the user
    preparation_steps: Optional[List[str]] = None  # For tests
    summary: Optional[str] = None         # For articles
    processing_time_ms: Optional[int] = None
