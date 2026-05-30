"""Tekmetric write-back job — same queue+worker pattern as AutoGenJob.

Frontend submits the finished estimate; backend enqueues this document; the
VPS worker claims it, runs `EstimaroAgent.portals.tekmetric.push_estimate()`,
and posts back the RO number / URL the vision-agent captured. The frontend
polls until status is `success` or `failed` and then links the advisor
straight to the new Repair Order in Tekmetric.
"""
from beanie import Document
from pydantic import Field
from datetime import datetime
from typing import Optional
import uuid


JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"


class TekmetricPushJob(Document):
    job_id: str = Field(default_factory=lambda: f"tek_{uuid.uuid4().hex[:12]}")

    # Optional link back to the originating Estimate so a successful push can
    # stamp tekmetric_id on it.
    estimate_id: Optional[str] = None

    # The frontend submits a *complete* estimate snapshot; we persist the
    # whole payload so the worker can build the agent task without needing
    # to re-fetch from any other collection.
    estimate: dict = Field(default_factory=dict)

    status: str = JOB_QUEUED
    progress: str = "Queued"
    progress_pct: int = 0

    worker_id: Optional[str] = None
    attempts: int = 0

    result: dict = Field(default_factory=dict)
    error: str = ""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Settings:
        name = "tekmetric_push_jobs"
