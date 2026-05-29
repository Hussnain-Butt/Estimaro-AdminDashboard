"""API request/response schemas for auto-generate jobs (separate from Document)."""
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from typing import Optional, List, Any, Dict


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


class JobSubmitRequest(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17)
    serviceRequest: str = Field(..., min_length=1)
    customerName: str = Field(..., min_length=1)
    customerEmail: Optional[EmailStr] = None
    customerPhone: str = Field(..., min_length=10)
    odometer: Optional[int] = Field(None, ge=0)
    laborRate: Optional[float] = 150.0
    partsMarkup: Optional[float] = 30.0
    taxRate: Optional[float] = 0.0925


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkerProgressUpdate(BaseModel):
    progress: str
    progress_pct: int = 0


class WorkerResultPayload(BaseModel):
    result: JobResult


class WorkerErrorPayload(BaseModel):
    error: str
