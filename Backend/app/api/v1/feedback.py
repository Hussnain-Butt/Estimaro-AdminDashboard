"""Estimate feedback endpoints — capture the advisor's voice/text feedback on a
specific estimate, and list it for the team to review.

Deliberately simple (v1): store the verbatim message + estimate context. No LLM
processing here — the value is the raw, anchored requirement; structuring can
come later. Auth-light to match the rest of the v1 surface (advisor-facing app
behind the shop's own login)."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import logging

import httpx

from app.core.config import settings
from app.models.estimate_feedback import (
    EstimateFeedback, FEEDBACK_NEW, FEEDBACK_REVIEWED, FEEDBACK_RESOLVED,
)

router = APIRouter()
log = logging.getLogger(__name__)

_ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
# Cap uploads — advisor feedback clips are short; reject anything that looks
# like a stuck/looping recording before we pay to transcribe it.
_MAX_AUDIO_BYTES = 12 * 1024 * 1024  # ~12 MB


@router.post("/transcribe", summary="Voice→text via ElevenLabs Scribe (server-proxied)")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe a short audio clip to text. The ElevenLabs key stays
    server-side (never shipped to the browser). Returns {text}. On any
    failure returns 503/502 so the frontend can fall back to typing."""
    if not settings.ELEVENLABS_API_KEY:
        raise HTTPException(503, "Speech-to-text not configured (ELEVENLABS_API_KEY unset)")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty audio")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                _ELEVENLABS_STT_URL,
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
                data={"model_id": settings.ELEVENLABS_STT_MODEL},
                files={"file": (file.filename or "audio.webm",
                                audio, file.content_type or "audio/webm")},
            )
    except Exception as e:
        log.error(f"ElevenLabs STT request failed: {e}")
        raise HTTPException(502, "Transcription service unreachable")
    if resp.status_code >= 400:
        log.error(f"ElevenLabs STT {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(502, f"Transcription failed ({resp.status_code})")
    data = resp.json()
    return {"text": (data.get("text") or "").strip(),
            "language": data.get("language_code")}


@router.get("/voice-agent", summary="Mint a signed URL for the voice feedback agent")
async def voice_agent():
    """Return the Conversational AI agent_id + a short-lived signed WebSocket URL
    so the browser can start a live two-way voice conversation WITHOUT ever
    seeing the API key (the mint happens here, server-side)."""
    if not settings.ELEVENLABS_API_KEY:
        raise HTTPException(503, "Voice agent not configured (ELEVENLABS_API_KEY unset)")
    aid = settings.ELEVENLABS_AGENT_ID
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
                params={"agent_id": aid},
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            )
    except Exception as e:
        log.error(f"ElevenLabs signed-url request failed: {e}")
        raise HTTPException(502, "Voice agent service unreachable")
    if resp.status_code >= 400:
        log.error(f"ElevenLabs signed-url {resp.status_code}: {resp.text[:200]}")
        raise HTTPException(502, f"Voice agent unavailable ({resp.status_code})")
    return {"agent_id": aid, "signed_url": resp.json().get("signed_url")}


class ConversationSave(BaseModel):
    transcript: str
    conversation_id: Optional[str] = None
    job_id: Optional[str] = None
    estimate_id: Optional[str] = None
    vin: Optional[str] = None
    vehicle: Optional[str] = None
    service_request: Optional[str] = None
    estimate_total: Optional[float] = None
    estimate_source: Optional[str] = None
    match_tier: Optional[str] = None
    advisor_name: Optional[str] = None


@router.post("/conversation", summary="Save a completed voice-agent conversation as feedback")
async def save_conversation(payload: ConversationSave):
    """Persist the transcript of a voice-agent call as an estimate-feedback
    record (input_mode='voice_agent') so it shows up on the Feedback page like
    any other feedback — this is the 'note the conversation' half."""
    msg = (payload.transcript or "").strip()
    if not msg:
        raise HTTPException(400, "Empty transcript")
    d = payload.model_dump()
    d["message"] = d.pop("transcript")
    d["input_mode"] = "voice_agent"
    fb = EstimateFeedback(**d)
    await fb.insert()
    return {"ok": True, "feedback_id": fb.feedback_id}


class FeedbackSubmit(BaseModel):
    message: str
    input_mode: str = "voice"
    job_id: Optional[str] = None
    estimate_id: Optional[str] = None
    vin: Optional[str] = None
    vehicle: Optional[str] = None
    service_request: Optional[str] = None
    estimate_total: Optional[float] = None
    estimate_source: Optional[str] = None
    match_tier: Optional[str] = None
    advisor_name: Optional[str] = None


@router.post("", summary="Submit advisor feedback on an estimate")
async def submit_feedback(payload: FeedbackSubmit):
    msg = (payload.message or "").strip()
    if not msg:
        raise HTTPException(400, "Feedback message is empty")
    fb = EstimateFeedback(**payload.model_dump())
    fb.message = msg
    await fb.insert()
    return {"ok": True, "feedback_id": fb.feedback_id}


@router.get("", summary="List estimate feedback (newest first)")
async def list_feedback(status: Optional[str] = None, limit: int = 100):
    q = EstimateFeedback.find()
    if status:
        q = EstimateFeedback.find(EstimateFeedback.status == status)
    rows = await q.sort(-EstimateFeedback.created_at).limit(min(limit, 500)).to_list()
    return {"count": len(rows), "items": [r.model_dump() for r in rows]}


class FeedbackStatusUpdate(BaseModel):
    status: str


@router.patch("/{feedback_id}", summary="Update feedback review status")
async def update_status(feedback_id: str, payload: FeedbackStatusUpdate):
    if payload.status not in (FEEDBACK_NEW, FEEDBACK_REVIEWED, FEEDBACK_RESOLVED):
        raise HTTPException(400, f"Invalid status {payload.status!r}")
    fb = await EstimateFeedback.find_one(EstimateFeedback.feedback_id == feedback_id)
    if not fb:
        raise HTTPException(404, "Feedback not found")
    fb.status = payload.status
    await fb.save()
    return {"ok": True}
