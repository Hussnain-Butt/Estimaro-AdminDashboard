"""Pydantic models for the estimation pipeline."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


SystemType = Literal[
    "braking", "engine", "transmission", "suspension",
    "electrical", "hvac", "exhaust", "cooling", "steering", "other"
]
Severity = Literal["low", "medium", "high", "critical"]

_SYSTEMS = {
    "braking", "engine", "transmission", "suspension",
    "electrical", "hvac", "exhaust", "cooling", "steering", "other",
}
_SEVERITIES = {"low", "medium", "high", "critical"}


class JobSpec(BaseModel):
    """Parsed from Hermes output. Hermes is a small model and occasionally
    returns null / unexpected values, so every field is lenient: a missing or
    invalid value falls back to a safe default instead of raising."""
    system: str = "other"
    subsystem: str = ""
    symptom: str = ""
    severity: str = "medium"
    keywords: list[str] = Field(default_factory=list)
    needs_diagnosis: bool = False

    @field_validator("system", "subsystem", "symptom", "severity", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        # None / numbers / etc. -> string; None -> "" (field defaults applied below)
        return "" if v is None else str(v)

    @field_validator("system")
    @classmethod
    def _valid_system(cls, v):
        return v if v in _SYSTEMS else "other"

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v):
        return v if v in _SEVERITIES else "medium"


class VehicleFingerprint(BaseModel):
    vin: str
    year: int
    make: str
    model: str
    trim: Optional[str] = None
    engine: Optional[str] = None
    transmission: Optional[str] = None
    raw_vpic: dict = Field(default_factory=dict)


class LaborResult(BaseModel):
    operation: str
    hours: float
    source: str
    vehicle_match: dict
    raw_text: Optional[str] = None
    screenshot_path: Optional[str] = None


class PartResult(BaseModel):
    name: str
    oem_number: Optional[str] = None
    price: Optional[float] = None
    vendor: str
    in_stock: Optional[bool] = None
    source: str
    screenshot_path: Optional[str] = None


class VerificationResult(BaseModel):
    match: bool
    confidence: float
    reason: str
    issues: list[str] = Field(default_factory=list)


class EstimateResult(BaseModel):
    job_spec: JobSpec
    vehicle: VehicleFingerprint
    labor: list[LaborResult] = Field(default_factory=list)
    parts: list[PartResult] = Field(default_factory=list)
    confidence: float = 0.0
    needs_human_review: bool = False
    notes: list[str] = Field(default_factory=list)
