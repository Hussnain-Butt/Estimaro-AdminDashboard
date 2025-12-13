"""
Tekmetric Integration API Routes

Endpoints for pushing estimates to Tekmetric shop management system.
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from decimal import Decimal

from app.services.tekmetric_service import tekmetric_service

router = APIRouter()


class TekmetricPushRequest(BaseModel):
    """Request to push estimate to Tekmetric"""
    customer: Dict = Field(..., description="Customer info (name, phone, email)")
    vehicleInfo: Dict = Field(..., description="Vehicle info (vin, year, make, model)")
    laborItems: List[Dict] = Field(default_factory=list, description="Labor items")
    partsItems: List[Dict] = Field(default_factory=list, description="Parts items")
    breakdown: Dict = Field(..., description="Calculation breakdown")
    odometer: Optional[int] = Field(None, description="Odometer reading")
    
    class Config:
        json_schema_extra = {
            "example": {
                "customer": {
                    "name": "John Doe",
                    "phone": "+1-555-123-4567",
                    "email": "john@example.com"
                },
                "vehicleInfo": {
                    "vin": "1HGBH41JXMN109186",
                    "year": 2021,
                    "make": "Honda",
                    "model": "Accord"
                },
                "laborItems": [
                    {"description": "Brake Pad Replacement", "hours": "1.2", "rate": "150", "total": "180.00"}
                ],
                "partsItems": [
                    {"description": "Brake Pads", "partNumber": "BRK-001", "quantity": "1", "cost": "89.99", "total": "116.99"}
                ],
                "breakdown": {
                    "laborTotal": "180.00",
                    "partsTotal": "116.99",
                    "subtotal": "296.99",
                    "taxAmount": "27.47",
                    "total": "324.46"
                }
            }
        }


@router.post(
    "/push",
    summary="Push estimate to Tekmetric",
    description="Push a complete estimate to Tekmetric, creating customer, vehicle, and repair order."
)
async def push_to_tekmetric(request: TekmetricPushRequest):
    """
    Push estimate to Tekmetric shop management system.
    
    This endpoint:
    1. Creates or finds customer in Tekmetric
    2. Creates or finds vehicle in Tekmetric
    3. Creates repair order with estimate status
    4. Adds labor and parts line items
    
    Returns:
    - RO number
    - Estimate ID
    - View URL
    """
    try:
        result = await tekmetric_service.push_estimate({
            "customer": request.customer,
            "vehicleInfo": request.vehicleInfo,
            "laborItems": request.laborItems,
            "partsItems": request.partsItems,
            "breakdown": request.breakdown,
            "odometer": request.odometer
        })
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to push to Tekmetric")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tekmetric integration error: {str(e)}"
        )


class UpdateROStatusRequest(BaseModel):
    """Request to update RO status"""
    ro_id: str = Field(..., description="Tekmetric RO ID")
    status: str = Field(..., description="New status")


@router.patch(
    "/status",
    summary="Update RO status",
    description="Update repair order status in Tekmetric"
)
async def update_ro_status(request: UpdateROStatusRequest):
    """Update repair order status."""
    try:
        result = await tekmetric_service.update_ro_status(
            ro_id=request.ro_id,
            status=request.status
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to update status")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
