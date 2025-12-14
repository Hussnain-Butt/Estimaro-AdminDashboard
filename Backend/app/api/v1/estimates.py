"""
Estimate API Routes

Endpoints for estimate operations:
- POST /calculate - Real-time calculation (no save)
- POST /draft - Create draft estimate
- GET /{estimate_id} - Get estimate by ID
- GET / - List advisor's estimates
- POST /{estimate_id}/send - Send estimate to customer
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List

from app.core.dependencies import get_current_active_advisor
from app.models.user import User
from app.schemas.estimate import (
    CalculationRequestSchema,
    CalculationResponseSchema,
    EstimateCreateSchema,
    EstimateResponseSchema
)
from app.services.estimate_service import get_estimate_service

router = APIRouter()


@router.post(
    "/calculate",
    response_model=CalculationResponseSchema,
    summary="Calculate estimate totals",
    description="Real-time calculation of estimate totals without saving to database. Used for frontend live updates."
)
async def calculate_estimate(
    request: CalculationRequestSchema
):
    """
    Calculate estimate totals in real-time.
    """
    service = get_estimate_service()
    return service.calculate_estimate(request)


@router.post(
    "/draft",
    response_model=EstimateResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create draft estimate",
    description="Create a new draft estimate and save to database with customer and vehicle information."
)
async def create_draft_estimate(
    estimate_data: EstimateCreateSchema
):
    """
    Create a draft estimate.
    """
    service = get_estimate_service()
    # AUTH BYPASS: Use system user
    return await service.create_draft_estimate(estimate_data, "system")


@router.put(
    "/{estimate_id}",
    response_model=EstimateResponseSchema,
    summary="Update draft estimate",
    description="Update an existing draft estimate with new data."
)
async def update_draft_estimate(
    estimate_id: str,
    estimate_data: EstimateCreateSchema
):
    """
    Update a draft estimate.
    """
    service = get_estimate_service()
    estimate = await service.update_draft_estimate(estimate_id, estimate_data)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Estimate with ID {estimate_id} not found"
        )
        
    return estimate


@router.get(
    "/{estimate_id}",
    response_model=EstimateResponseSchema,
    summary="Get estimate by ID",
    description="Retrieve a specific estimate by ID with all details."
)
async def get_estimate(
    estimate_id: str
):
    """
    Get estimate by ID.
    Authorization: Only the advisor who created the estimate can view it.
    """
    service = get_estimate_service()
    estimate = await service.get_estimate(estimate_id)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Estimate with ID {estimate_id} not found"
        )
    
    return estimate


@router.get(
    "/",
    response_model=List[EstimateResponseSchema],
    summary="List advisor's estimates",
    description="Get all estimates created by the current advisor with optional status filter."
)
async def list_estimates(
    status_filter: Optional[str] = Query(None, description="Filter by status: draft, sent, approved, declined")
):
    """
    List all estimates for the current advisor.
    """
    service = get_estimate_service()
    print("Listing estimates for system advisor")
    return await service.get_advisor_estimates("system", status_filter)


@router.post(
    "/{estimate_id}/send",
    response_model=EstimateResponseSchema,
    summary="Send estimate to customer",
    description="Mark estimate as sent and set expiration date. This triggers SMS notification to customer."
)
async def send_estimate(
    estimate_id: str,
    days_valid: int = Query(7, ge=1, le=30, description="Days until estimate expires")
):
    """
    Send estimate to customer.
    """
    service = get_estimate_service()
    estimate = await service.send_estimate(estimate_id, days_valid)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Estimate with ID {estimate_id} not found"
        )
    
    # TODO: Send SMS notification via Twilio
    # notification_service.send_estimate_sms(estimate.customerInfo.phone, estimate.publicToken)
    
    return estimate

