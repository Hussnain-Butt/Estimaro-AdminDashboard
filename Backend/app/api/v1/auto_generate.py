"""
Auto-Generate Estimate API Routes

Single endpoint that auto-generates complete estimate from intake information.
Now includes: recall check, warranty check, vendor scoring, part conditions, cleaning kits.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict
from decimal import Decimal

from app.core.database import get_db
from app.services.auto_generate_service import auto_generate_service

router = APIRouter()


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
    request: AutoGenerateRequest,
    db: Session = Depends(get_db)
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-generation failed: {str(e)}"
        )
