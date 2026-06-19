"""Estimate feedback endpoints — capture the advisor's voice/text feedback on a
specific estimate, and list it for the team to review.

Deliberately simple (v1): store the verbatim message + estimate context. No LLM
processing here — the value is the raw, anchored requirement; structuring can
come later. Auth-light to match the rest of the v1 surface (advisor-facing app
behind the shop's own login)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.models.estimate_feedback import (
    EstimateFeedback, FEEDBACK_NEW, FEEDBACK_REVIEWED, FEEDBACK_RESOLVED,
)

router = APIRouter()


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
