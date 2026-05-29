"""Auto-Generate Job document."""
from beanie import Document, Indexed
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid


# --- API schemas only (NOT stored as nested documents) ---

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
    vehicleInfo: VehicleInfo = Field(default_factory=VehicleInfo)
    laborItems: List[LaborLine] = Field(default_factory=list)
    partsItems: List[PartLine] = Field(default_factory=list)
    breakdown: Breakdown = Field(default_factory=Breakdown)
    section_path: Optional[str] = None
    extraction_confidence: float = 0.0
    verification_match: bool = False
    verification_confidence: float = 0.0
    verification_reason: Optional[str] = None
    agent_steps: int = 0
    elapsed_sec: float = 0.0


# Plain string status (no Enum on document — avoids init quirks)
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"


# Backwards-compat alias for routes (str-enum-like)
class JobStatus(str):
    QUEUED = JOB_QUEUED
    RUNNING = JOB_RUNNING
    SUCCESS = JOB_SUCCESS
    FAILED = JOB_FAILED


class AutoGenJob(Document):
    job_id: str = Indexed(str, unique=True, default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")

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
        use_state_management = True
