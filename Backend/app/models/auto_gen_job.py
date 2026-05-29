"""Auto-Generate Job document — minimal Beanie shape."""
from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
from typing import Optional, Dict, Any
import uuid


JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"


class AutoGenJob(Document):
    job_id: str = Indexed(unique=True, default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")

    vin: str = ""
    serviceRequest: str = ""
    customerName: str = ""
    customerEmail: Optional[str] = None
    customerPhone: str = ""
    odometer: Optional[int] = None
    laborRate: float = 150.0
    partsMarkup: float = 30.0
    taxRate: float = 0.0925

    status: str = JOB_QUEUED
    progress: str = "Queued"
    progress_pct: int = 0

    worker_id: Optional[str] = None
    attempts: int = 0

    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Settings:
        name = "auto_gen_jobs"
