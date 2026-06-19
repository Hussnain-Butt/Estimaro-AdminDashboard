"""Estimate feedback — advisor's voice/text feedback on a specific generated
estimate.

This is the requirements-capture loop: the client (shop advisor) describes, in
their OWN words and anchored to a CONCRETE estimate, what's wrong or what they
want changed. Vague asks like "make it 90% better" become specific, reviewable
records tied to a real estimate — which is exactly what we need to act on, and
which also feeds estimate-quality improvements (matching, SOP gating, labor
times).
"""
from beanie import Document
from pydantic import Field
from datetime import datetime
from typing import Optional
import uuid


FEEDBACK_NEW = "new"
FEEDBACK_REVIEWED = "reviewed"
FEEDBACK_RESOLVED = "resolved"


class EstimateFeedback(Document):
    feedback_id: str = Field(default_factory=lambda: f"fb_{uuid.uuid4().hex[:12]}")

    # What the advisor said — transcribed from voice (editable before submit)
    # and/or typed. The raw, unprocessed words: the whole point is to capture
    # the domain expert's intent verbatim.
    message: str = ""
    input_mode: str = "voice"   # "voice" | "text" | "voice_agent"
    # Set when the feedback came from a two-way voice-agent conversation, so we
    # can pull the full call record from ElevenLabs later if needed.
    conversation_id: Optional[str] = None

    # Estimate context this feedback is anchored to — so we know EXACTLY which
    # estimate / vehicle / service the advisor is talking about.
    job_id: Optional[str] = None
    estimate_id: Optional[str] = None
    vin: Optional[str] = None
    vehicle: Optional[str] = None           # "2023 Mercedes-Benz C-Class"
    service_request: Optional[str] = None   # the original complaint
    estimate_total: Optional[float] = None
    estimate_source: Optional[str] = None   # "historical" | "live" (None if unknown)
    match_tier: Optional[str] = None        # exact_vin / service_type / keyword

    advisor_name: Optional[str] = None

    status: str = FEEDBACK_NEW
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "estimate_feedback"
