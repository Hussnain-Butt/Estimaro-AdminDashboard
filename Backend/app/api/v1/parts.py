"""
Parts API Routes

Endpoints for parts lookup:
- POST /search - Search for parts
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List
from app.services.parts_service import parts_service
from app.adapters.parts_adapter_interface import PartResult

router = APIRouter()


class PartsSearchRequest(BaseModel):
    """Request schema for parts search"""
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
    "/search",
    response_model=List[PartResult],
    summary="Search for parts",
    description="Search for parts based on VIN and job description. Currently uses mock data, will integrate with PartsLink24 when API keys are available."
)
async def search_parts(request: PartsSearchRequest):
    """
    Search for parts.
    
    **Current Implementation:** Mock adapter with 15+ common parts
    **Future:** PartsLink24 integration
    
    **Supported Parts (Mock):**
    - Brake Pads, Rotors, Calipers (OEM & Aftermarket)
    - Oil, Oil Filter, Air Filter, Cabin Filter
    - Timing Belt Kit
    - Shock Absorbers, Struts
    - Battery, Alternator, Starter
    - Coolant
    
    **Returns:**
    - List of matching parts with:
      - Part number
      - Description
      - Manufacturer/Brand
      - Estimated price
      - OEM vs Aftermarket flag
      - Category
    """
    try:
        results = await parts_service.search_parts(
            vin=request.vin,
            job_description=request.jobDescription
        )
        
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search parts: {str(e)}"
        )
