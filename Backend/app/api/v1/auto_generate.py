"""
Auto-Generate Estimate API Routes

Two flows:
  1. Legacy synchronous `/generate` — runs old scraper service inline.
  2. NEW async queue `/jobs` — frontend submits, worker on VPS picks up,
     runs the ALLDATA vision agent, posts result back. Frontend polls.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, List
from decimal import Decimal

from app.core.config import settings
from app.models.auto_gen_job import (
    AutoGenJob, JOB_QUEUED, JOB_RUNNING, JOB_SUCCESS, JOB_FAILED,
)
from app.schemas.auto_gen_job_schemas import (
    JobSubmitRequest, JobSubmitResponse, JobStatusResponse,
    WorkerProgressUpdate, WorkerResultPayload, WorkerErrorPayload,
)
from app.services.auto_generate_service import auto_generate_service
import traceback
import os

router = APIRouter()


# ============================================================================
# Worker auth helper
# ============================================================================
def _require_worker_secret(x_worker_secret: Optional[str]):
    if not x_worker_secret or x_worker_secret != settings.AGENT_WORKER_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bad worker secret")


class VendorWeightsRequest(BaseModel):
    """Vendor scoring weights"""
    brand: int = Field(40, ge=0, le=100, description="Brand quality weight")
    price: int = Field(35, ge=0, le=100, description="Price weight")
    distance: int = Field(25, ge=0, le=100, description="Distance weight")


class AutoGenerateRequest(BaseModel):
    """Request schema for auto-generate estimate"""
    vin: str = Field(..., min_length=17, max_length=17, description="Vehicle VIN")
    serviceRequest: str = Field(..., min_length=1, description="Customer's service request")
    customerName: str = Field(..., min_length=1, description="Customer name")
    customerEmail: Optional[EmailStr] = Field(None, description="Customer email")
    customerPhone: str = Field(..., min_length=10, description="Customer phone")
    odometer: Optional[int] = Field(None, ge=0, description="Odometer reading")
    laborRate: Optional[Decimal] = Field(Decimal("150"), ge=0, description="Shop labor rate")
    partsMarkup: Optional[Decimal] = Field(Decimal("30"), ge=0, le=100, description="Parts markup %")
    taxRate: Optional[Decimal] = Field(Decimal("0.0925"), ge=0, le=1, description="Tax rate")
    vendorWeights: Optional[VendorWeightsRequest] = Field(None, description="Vendor scoring weights")
    
    class Config:
        json_schema_extra = {
            "example": {
                "vin": "1HGBH41JXMN109186",
                "serviceRequest": "Brake pads replacement",
                "customerName": "John Doe",
                "customerEmail": "john.doe@example.com",
                "customerPhone": "+1-555-123-4567",
                "odometer": 45000,
                "laborRate": "150",
                "partsMarkup": "30",
                "taxRate": "0.0925",
                "vendorWeights": {
                    "brand": 40,
                    "price": 35,
                    "distance": 25
                }
            }
        }


@router.post(
    "/generate",
    summary="Auto-generate complete estimate",
    description="""
    One-click estimate generation! Provide VIN, service request, and customer info.
    
    **Complete Workflow:**
    1. ✅ Decode VIN → Get vehicle details
    2. ✅ Check NHTSA Recalls → Flag safety concerns
    3. ✅ Check Warranty → Alert if under factory warranty
    4. ✅ Lookup Labor Times → ALLDATA integration
    5. ✅ Search Parts → PartsLink24 integration
    6. ✅ Compare Vendors → Worldpac/SSF scoring
    7. ✅ Detect Part Conditions → NEW/REMAN (CA BAR compliance)
    8. ✅ Calculate Totals → With cleaning kits
    """
)
async def auto_generate_estimate(
    request: AutoGenerateRequest
):
    """
    Auto-generate complete estimate from intake information.
    
    **New Features:**
    - NHTSA Recall Check with complaint matching
    - Warranty Math Check (Bumper-to-Bumper, Powertrain)
    - Vendor Scoring with configurable weights
    - Part Condition Detection (NEW/REMANUFACTURED)
    - Service Cleaning Kits (replaces shop fees)
    - Confidence Scoring
    
    **Returns:**
    - Complete estimate data with all workflow steps
    - Flags for recalls, warranty alerts, unknown conditions
    - Vendor comparison with scores
    - Confidence score and recommended action
    """
    try:
        # Prepare vendor weights
        vendor_weights = None
        if request.vendorWeights:
            vendor_weights = {
                "brand": request.vendorWeights.brand,
                "price": request.vendorWeights.price,
                "distance": request.vendorWeights.distance
            }
        
        # Run auto-generation workflow
        result = await auto_generate_service.generate_estimate(
            vin=request.vin,
            service_request=request.serviceRequest,
            customer_name=request.customerName,
            customer_phone=request.customerPhone,
            customer_email=request.customerEmail or "",
            odometer=request.odometer or 0,
            labor_rate=request.laborRate or Decimal("150"),
            parts_markup=request.partsMarkup or Decimal("30"),
            tax_rate=request.taxRate or Decimal("0.0925"),
            vendor_weights=vendor_weights
        )
        
        return result
        
    except Exception as e:
        # Debug logging
        with open("error_log.txt", "w") as f:
            f.write(str(e))
            f.write("\n")
            f.write(traceback.format_exc())
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-generation failed: {str(e)}"
        )


# ============================================================================
# NEW: Async job queue (frontend → backend → worker → backend → frontend)
# (Request/response schemas live in app.schemas.auto_gen_job_schemas)
# ============================================================================

@router.post(
    "/jobs",
    response_model=JobSubmitResponse,
    summary="Submit auto-generate job to the agent queue",
    description="Frontend submits VIN+complaint+customer. Returns job_id. "
                "Poll GET /jobs/{job_id} until status is 'success' or 'failed'.",
)
async def submit_job(req: JobSubmitRequest):
    job = AutoGenJob(
        vin=req.vin.strip().upper(),
        serviceRequest=req.serviceRequest.strip(),
        customerName=req.customerName.strip(),
        customerEmail=req.customerEmail,
        customerPhone=req.customerPhone.strip(),
        odometer=req.odometer,
        laborRate=req.laborRate or 150.0,
        partsMarkup=req.partsMarkup or 30.0,
        taxRate=req.taxRate or 0.0925,
        progress="Queued — waiting for agent",
        progress_pct=5,
    )
    await job.insert()
    return JobSubmitResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        progress_pct=job.progress_pct,
        created_at=job.created_at,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get current state of an auto-generate job",
)
async def get_job(job_id: str):
    job = await AutoGenJob.find_one(AutoGenJob.job_id == job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        progress_pct=job.progress_pct,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=job.result,
        error=job.error,
    )


@router.get(
    "/jobs",
    response_model=List[JobStatusResponse],
    summary="List recent jobs (last 50)",
)
async def list_jobs(status_filter: Optional[str] = Query(None)):
    q = AutoGenJob.find()
    if status_filter:
        q = AutoGenJob.find(AutoGenJob.status == status_filter)
    jobs = await q.sort("-created_at").limit(50).to_list()
    return [
        JobStatusResponse(
            job_id=j.job_id, status=j.status, progress=j.progress, progress_pct=j.progress_pct,
            created_at=j.created_at, started_at=j.started_at, completed_at=j.completed_at,
            result=j.result, error=j.error,
        ) for j in jobs
    ]


# ---------- worker-only endpoints ----------

@router.get(
    "/jobs/pending/next",
    response_model=Optional[JobStatusResponse],
    summary="WORKER: claim the next queued job",
)
async def worker_claim_next(
    worker_id: str = Query(..., min_length=1),
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await AutoGenJob.find_one(AutoGenJob.status == JOB_QUEUED, sort=[("created_at", 1)])
    if not job:
        return None
    job.status = JOB_RUNNING
    job.worker_id = worker_id
    job.attempts += 1
    job.started_at = datetime.utcnow()
    job.progress = "Worker picked up — decoding VIN"
    job.progress_pct = 10
    await job.save()
    return JobStatusResponse(
        job_id=job.job_id, status=job.status, progress=job.progress, progress_pct=job.progress_pct,
        created_at=job.created_at, started_at=job.started_at, completed_at=job.completed_at,
        result=job.result, error=job.error,
    )


@router.post(
    "/jobs/{job_id}/progress",
    summary="WORKER: update progress message",
)
async def worker_progress(
    job_id: str,
    payload: WorkerProgressUpdate,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await AutoGenJob.find_one(AutoGenJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.progress = payload.progress
    job.progress_pct = max(min(payload.progress_pct, 99), job.progress_pct)
    await job.save()
    return {"ok": True}


@router.post(
    "/jobs/{job_id}/result",
    summary="WORKER: submit final result",
)
async def worker_result(
    job_id: str,
    payload: WorkerResultPayload,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await AutoGenJob.find_one(AutoGenJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.result = payload.result.model_dump()
    job.status = JOB_SUCCESS
    job.progress = "Completed"
    job.progress_pct = 100
    job.completed_at = datetime.utcnow()
    await job.save()
    return {"ok": True}


@router.post(
    "/jobs/{job_id}/fail",
    summary="WORKER: mark job as failed",
)
async def worker_fail(
    job_id: str,
    payload: WorkerErrorPayload,
    x_worker_secret: Optional[str] = Header(None, alias="X-Worker-Secret"),
):
    _require_worker_secret(x_worker_secret)
    job = await AutoGenJob.find_one(AutoGenJob.job_id == job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.error = payload.error
    job.status = JOB_FAILED
    job.progress = f"Failed: {payload.error[:80]}"
    job.progress_pct = 100
    job.completed_at = datetime.utcnow()
    await job.save()
    return {"ok": True}
