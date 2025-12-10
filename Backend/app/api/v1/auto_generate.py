"""
Auto-Generate Estimate API Routes

Single endpoint that auto-generates complete estimate from intake information.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from decimal import Decimal

from app.core.database import get_db
from app.services.auto_generate_service import auto_generate_service

router = APIRouter()


class AutoGenerateRequest(BaseModel):
    """Request schema for auto-generate estimate"""
    vin: str = Field(..., min_length=17, max_length=17, description="Vehicle VIN")
    serviceRequest: str = Field(..., min_length=1, description="Customer's service request")
    customerName: str = Field(..., min_length=1, description="Customer name")
    customerEmail: Optional[EmailStr] = Field(None, description="Customer email")
    customerPhone: str = Field(..., min_length=10, description="Customer phone")
    odometer: Optional[int] = Field(None, ge=0, description="Odometer reading")
    laborRate: Optional[Decimal] = Field(Decimal("150"), ge=0, description="Shop labor rate")
    
    class Config:
        json_schema_extra = {
            "example": {
                "vin": "1HGBH41JXMN109186",
                "serviceRequest": "Brake pads replacement",
                "customerName": "John Doe",
                "customerEmail": "john.doe@example.com",
                "customerPhone": "+1-555-123-4567",
                "odometer": 45000,
                "laborRate": "150"
            }
        }


@router.post(
    "/generate",
    summary="Auto-generate complete estimate",
    description="One-click estimate generation! Provide VIN, service request, and customer info. System automatically: decodes VIN, looks up labor times, searches parts, compares vendors, and calculates totals."
)
async def auto_generate_estimate(
    request: AutoGenerateRequest,
    db: Session = Depends(get_db)
):
    """
    Auto-generate complete estimate from intake information.
    
    **Workflow:**
    1. ✅ Decode VIN → Get vehicle details (NHTSA)
    2. ✅ Service Request → Lookup labor times (ALLDATA/Mock)
    3. ✅ Labor Items → Search required parts (PartsLink24/Mock)
    4. ✅ Parts → Compare vendors (Worldpac/SSF) - Coming soon
    5. ✅ Calculate → Final estimate with totals
    
    **Returns:**
    - Complete estimate data
    - Step-by-step results
    - Any errors encountered
    
    **Example Response:**
    ```json
    {
      "success": true,
      "estimate_data": {
        "vehicleInfo": {...},
        "laborItems": [...],
        "partsItems": [...],
        "breakdown": {...}
      },
      "steps": {
        "vehicle_decode": {"success": true, "data": {...}},
        "labor_lookup": {"success": true, "data": {...}},
        "parts_search": {"success": true, "data": {...}},
        "calculation": {"success": true, "data": {...}}
      }
    }
    ```
    """
    try:
        # Run auto-generation workflow
        result = await auto_generate_service.generate_estimate(
            vin=request.vin,
            service_request=request.serviceRequest,
            labor_rate=request.laborRate or Decimal("150")
        )
        
        # Add customer info to result
        result["customer_info"] = {
            "name": request.customerName,
            "email": request.customerEmail,
            "phone": request.customerPhone,
            "odometer": request.odometer
        }
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-generation failed: {str(e)}"
        )
