"""Auto-Generate Job document — minimal Beanie shape."""
from beanie import Document
from pydantic import Field
from datetime import datetime
from typing import Optional
import uuid


JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"

# Job mode — a full estimate build, or an on-demand vendor price refresh of an
# existing estimate's parts (advisor-triggered; runs the vendor lookup only,
# never ALLDATA). Same queue / claim / progress / result lifecycle for both.
JOB_MODE_ESTIMATE = "estimate"
JOB_MODE_REFRESH = "price_refresh"


class AutoGenJob(Document):
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")

    vin: str = ""
    serviceRequest: str = ""
    customerName: str = ""
    customerEmail: Optional[str] = None
    customerPhone: str = ""
    odometer: Optional[int] = None
    laborRate: float = 150.0
    partsMarkup: float = 30.0
    taxRate: float = 0.0925

    # Job mode + payload for the price-refresh mode (the parts to reprice +
    # vehicle context). Empty for normal estimate jobs.
    mode: str = JOB_MODE_ESTIMATE
    refresh_payload: dict = Field(default_factory=dict)

    status: str = JOB_QUEUED
    progress: str = "Queued"
    progress_pct: int = 0

    worker_id: Optional[str] = None
    attempts: int = 0

    # Stored as JSON-serialisable dict; default empty dict avoids Optional schema issues
    result: dict = Field(default_factory=dict)
    error: str = ""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Settings:
        name = "auto_gen_jobs_v3"
