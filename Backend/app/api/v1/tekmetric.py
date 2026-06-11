"""Tekmetric Integration API — queue-based vision-agent push.

The shop's actual write-back happens inside a Chrome browser running on the
VPS worker, where the shop is already logged into Tekmetric. The flow:

  Frontend POST  /tekmetric/push       (compat) or
                 /tekmetric/jobs       (canonical)
                              → enqueues TekmetricPushJob, returns job_id
  Worker polls   /tekmetric/jobs/pending/next
                              → claims, runs portals.tekmetric.push_estimate()
                              → POSTs back result with RO# + ro_url
  Frontend polls /tekmetric/jobs/{id}
                              → status: success / failed → renders RO link

Returning a "fake success" without actually creating an RO (the previous
behaviour when no API key was configured) was the bug this rewire fixes.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.tekmetric_push_job import (
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_SUCCESS,
    TekmetricPushJob,
)


router = APIRouter()


# ---- shared helpers ------------------------------------------------------

WORKER_SECRET = os.environ.get("WORKER_SECRET", "")


def _require_worker_secret(x_worker_secret: Optional[str]) -> None:
    if WORKER_SECRET and x_worker_secret != WORKER_SECRET:
        raise HTTPException(status_code=401, detail="Bad worker secret")


# ---- schemas -------------------------------------------------------------


class TekmetricPushRequest(BaseModel):
    """Same shape the Frontend's pushToTekmetric() has always sent. Free-
    form on purpose — the worker rebuilds the agent prompt from this."""
    customer: dict
    vehicleInfo: dict
    laborItems: list = Field(default_factory=list)
    partsItems: list = Field(default_factory=list)
    breakdown: dict = Field(default_factory=dict)
    odometer: Optional[int] = None
    estimateId: Optional[str] = None
    # Original customer complaint — the worker ingests the approved estimate
    # into the historical corpus after a successful push, indexed by this.
    serviceRequest: Optional[str] = None


class TekmetricJobSubmitResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime


class TekmetricJobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: dict = Field(default_factory=dict)
    error: str = ""


class TekmetricWorkerClaimResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime
    started_at: Optional[datetime] = None
    estimate: dict
    estimate_id: Optional[str] = None


class TekmetricProgressUpdate(BaseModel):
    progress: str
    progress_pct: int = 0


class TekmetricResultPayload(BaseModel):
    ok: bool = True
    ro_number: str
    ro_url: Optional[str] = None
    customer_action: Optional[str] = None
    vehicle_action: Optional[str] = None
    labor_lines_added: Optional[int] = None
    parts_lines_added: Optional[int] = None
    note: Optional[str] = None


class TekmetricErrorPayload(BaseModel):
    error: str


# ---- frontend submit + poll ---------------------------------------------


async def _enqueue(req: TekmetricPushRequest) -> TekmetricPushJob:
    job = TekmetricPushJob(
        estimate_id=req.estimateId,
        estimate={
            "customer": req.customer,
            "vehicleInfo": req.vehicleInfo,
            "laborItems": req.laborItems,
            "partsItems": req.partsItems,
            "breakdown": req.breakdown,
            "odometer": req.odometer,
        },
        progress="Queued — waiting for the Tekmetric agent",
        progress_pct=5,
    )
    await job.insert()
    return job


@router.post(
    "/push",
    response_model=TekmetricJobSubmitResponse,
    summary="Push estimate to Tekmetric (compat: enqueues a vision-agent job)",
    description=(
        "Backwards-compatible endpoint kept for the existing frontend button. "
        "It now enqueues a write-back job that the VPS worker will execute "
        "with the Tekmetric vision agent. Returns `job_id` — poll "
        "GET /tekmetric/jobs/{job_id} until status is 'success' / 'failed'. "
        "The old immediate-mock response is gone — no fake RO numbers ever "
        "come back from this endpoint anymore."
    ),
)
async def push_to_tekmetric(req: TekmetricPushRequest):
    job = await _enqueue(req)
    return TekmetricJobSubmitResponse(
        job_id=job.job_id, status=job.status, progress=job.progress,
        progress_pct=job.progress_pct, created_at=job.created_at,
    )


@router.post(
    "/jobs",
    response_model=TekmetricJobSubmitResponse,
    summary="Submit a Tekmetric write-back job (canonical)",
)
async def submit_job(req: TekmetricPushRequest):
    job = await _enqueue(req)
    return TekmetricJobSubmitResponse(
        job_id=job.job_id, status=job.status, progress=job.progress,
        progress_pct=job.progress_pct, created_at=job.created_at,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=TekmetricJobStatusResponse,
    summary="Get current state of a Tekmetric job",
)
async def get_job(job_id: str):
    job = await TekmetricPushJob.find_one(TekmetricPushJob.job_id == job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return TekmetricJobStatusResponse(
        job_id=job.job_id, status=job.status, progress=job.progress,
        progress_pct=job.progress_pct, created_at=job.created_at,
        started_at=job.started_at, completed_at=job.completed_at,
        result=job.result, error=job.error,
    )


# ---- worker-only endpoints ----------------------------------------------


@router.get(
    "/jobs/pending/next",
    response_model=Optional[TekmetricWorkerClaimResponse],
    summary="WORKER: claim the next queued Tekmetric push job",
)
async def worker_claim_next(
    worker_id: str = Query(..., min_length=1),
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)

    # Stale recovery (same pattern as auto-generate). Tekmetric runs are
    # shorter than ALLDATA but a crashed worker can still leave one stuck.
    STALE_SECONDS = 900
    MAX_ATTEMPTS = 3
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_SECONDS)
    stale_jobs = await TekmetricPushJob.find(
        TekmetricPushJob.status == JOB_RUNNING,
        TekmetricPushJob.started_at < cutoff,
    ).to_list()
    for sj in stale_jobs:
        if sj.attempts >= MAX_ATTEMPTS:
            sj.status = JOB_FAILED
            sj.error = f"Abandoned after {sj.attempts} attempts"
            sj.progress = "Failed: abandoned after repeated worker failures"
            sj.progress_pct = 100
            sj.completed_at = datetime.utcnow()
        else:
            sj.status = JOB_QUEUED
            sj.progress = "Re-queued after a stale/abandoned run"
            sj.progress_pct = 5
        await sj.save()

    job = await TekmetricPushJob.find_one(
        TekmetricPushJob.status == JOB_QUEUED, sort=[("created_at", 1)],
    )
    if not job:
        return None
    job.status = JOB_RUNNING
    job.worker_id = worker_id
    job.attempts += 1
    job.started_at = datetime.utcnow()
    job.progress = "Worker picked up — opening Tekmetric"
    job.progress_pct = 10
    await job.save()
    return TekmetricWorkerClaimResponse(
        job_id=job.job_id, status=job.status, progress=job.progress,
        progress_pct=job.progress_pct, created_at=job.created_at,
        started_at=job.started_at, estimate=job.estimate,
        estimate_id=job.estimate_id,
    )


@router.post("/jobs/{job_id}/progress", summary="WORKER: update progress")
async def worker_progress(
    job_id: str,
    payload: TekmetricProgressUpdate,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await TekmetricPushJob.find_one(TekmetricPushJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.progress = payload.progress
    job.progress_pct = max(min(payload.progress_pct, 99), job.progress_pct)
    await job.save()
    return {"ok": True}


@router.post("/jobs/{job_id}/result", summary="WORKER: submit RO# result")
async def worker_result(
    job_id: str,
    payload: TekmetricResultPayload,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await TekmetricPushJob.find_one(TekmetricPushJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.result = payload.model_dump()
    job.status = JOB_SUCCESS
    job.progress = f"Created RO #{payload.ro_number}"
    job.progress_pct = 100
    job.completed_at = datetime.utcnow()
    await job.save()

    # Stamp the RO number back on the originating Estimate (best effort).
    if job.estimate_id:
        try:
            from app.models.estimate import Estimate
            est = await Estimate.find_one(Estimate.id == job.estimate_id)
            if est is not None:
                est.tekmetric_id = payload.ro_number
                await est.save()
        except Exception:
            pass
    return {"ok": True}


@router.post("/jobs/{job_id}/fail", summary="WORKER: mark job failed")
async def worker_fail(
    job_id: str,
    payload: TekmetricErrorPayload,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await TekmetricPushJob.find_one(TekmetricPushJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.error = payload.error
    job.status = JOB_FAILED
    job.progress = f"Failed: {payload.error[:80]}"
    job.progress_pct = 100
    job.completed_at = datetime.utcnow()
    await job.save()
    return {"ok": True}


# The legacy RO-status PATCH endpoint stays in place — it's used elsewhere
# and is unrelated to the push flow.

class UpdateROStatusRequest(BaseModel):
    ro_id: str
    status: str


@router.patch("/status", summary="Update RO status (legacy)")
async def update_ro_status(request: UpdateROStatusRequest):
    from app.services.tekmetric_service import tekmetric_service
    try:
        result = await tekmetric_service.update_ro_status(
            ro_id=request.ro_id, status=request.status,
        )
        if not result.get("success"):
            raise HTTPException(400, result.get("error", "Failed to update status"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
