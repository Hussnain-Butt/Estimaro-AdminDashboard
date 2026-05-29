"""
Auto-Generate Job document.

Queued estimate request that the off-Railway worker (Estimaro agent on VPS)
picks up, runs through the ALLDATA vision agent, and posts back.
"""
from beanie import Document, Indexed
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Any
import enum
import uuid


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class LaborLine(BaseModel):
    description: str
    hours: float
    rate: float
    total: float
    source: str = "ALLDATA"
    skill: Optional[str] = None


class PartLine(BaseModel):
    description: str
    partNumber: Optional[str] = None
    quantity: int = 1
    cost: float = 0.0
    markup: float = 0.0
    total: float = 0.0
    vendor: str = "ALLDATA"


class VehicleInfo(BaseModel):
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None


class Breakdown(BaseModel):
    laborTotal: float = 0.0
    partsTotal: float = 0.0
    subtotal: float = 0.0
    taxAmount: float = 0.0
    total: float = 0.0


class JobResult(BaseModel):
    vehicleInfo: VehicleInfo
    laborItems: List[LaborLine] = []
    partsItems: List[PartLine] = []
    breakdown: Breakdown
    section_path: Optional[str] = None
    extraction_confidence: float = 0.0
    verification_match: bool = False
    verification_confidence: float = 0.0
    verification_reason: Optional[str] = None
    agent_steps: int = 0
    elapsed_sec: float = 0.0


class AutoGenJob(Document):
    """Single auto-generate request, end-to-end audit trail."""

    # public id used everywhere
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")

    # input
    vin: str
    serviceRequest: str
    customerName: str
    customerEmail: Optional[str] = None
    customerPhone: str
    odometer: Optional[int] = None
    laborRate: float = 150.0
    partsMarkup: float = 30.0
    taxRate: float = 0.0925

    # lifecycle
    status: JobStatus = JobStatus.QUEUED
    progress: str = "Queued"          # short human-readable status
    progress_pct: int = 0             # 0-100

    # worker bookkeeping
    worker_id: Optional[str] = None
    attempts: int = 0

    # output
    result: Optional[JobResult] = None
    error: Optional[str] = None

    # timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Settings:
        name = "auto_gen_jobs"
        indexes = [
            "job_id",
            "status",
            "created_at",
        ]
