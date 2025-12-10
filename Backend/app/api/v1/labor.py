"""
Labor API Routes

Endpoints for labor time lookup:
- POST /lookup - Get labor time for a job
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.services.labor_service import labor_service
from app.adapters.labor_adapter_interface import LaborTimeResult

router = APIRouter()


class LaborLookupRequest(BaseModel):
    """Request schema for labor lookup"""
    vin: str = Field(..., min_length=17, max_length=17, description="Vehicle VIN")
    jobDescription: str = Field(..., min_length=1, description="Job description")
    
    class Config:
        json_schema_extra = {
            "example": {
                "vin": "1HGBH41JXMN109186",
                "jobDescription": "Brake Pad Replacement"
            }
        }


@router.post(
    "/lookup",
    response_model=LaborTimeResult,
    summary="Lookup labor time",
    description="Get standard labor time for a specific job. Currently uses mock data, will integrate with ALLDATA when API keys are available."
)
async def lookup_labor_time(request: LaborLookupRequest):
    """
    Lookup labor time for a job.
    
    **Current Implementation:** Mock adapter with 15+ common jobs
    **Future:** ALLDATA integration
    
    **Supported Jobs (Mock):**
    - Brake Pad/Rotor/Caliper Replacement
    - Oil Change, Transmission Fluid, Coolant Flush
    - Timing Belt Replacement
    - Shock/Strut Replacement
    - Battery, Alternator, Starter Replacement
    - Tire Rotation/Replacement
    - Air/Cabin Filter Replacement
    
    **Returns:**
    - Job description
    - Labor hours
    - Data source (mock/alldata)
    - Category and difficulty
    """
    try:
        result = await labor_service.get_labor_time(
            vin=request.vin,
            job_description=request.jobDescription
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Labor time not found for this job"
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to lookup labor time: {str(e)}"
        )
