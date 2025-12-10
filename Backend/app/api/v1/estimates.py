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
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
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
    request: CalculationRequestSchema,
    db: Session = Depends(get_db)
):
    """
    Calculate estimate totals in real-time.
    
    This endpoint performs calculations without saving to the database.
    Perfect for frontend real-time updates as the user adds/modifies items.
    
    **Formula:**
    - Labor Total = Σ(hours × rate)
    - Parts Total = Σ((cost × quantity) × (1 + markup/100))
    - Subtotal = Labor Total + Parts Total
    - Tax = Subtotal × tax_rate
    - Total = Subtotal + Tax
    """
    service = get_estimate_service(db)
    return service.calculate_estimate(request)


@router.post(
    "/draft",
    response_model=EstimateResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create draft estimate",
    description="Create a new draft estimate and save to database with customer and vehicle information."
)
async def create_draft_estimate(
    estimate_data: EstimateCreateSchema,
    current_user: User = Depends(get_current_active_advisor),
    db: Session = Depends(get_db)
):
    """
    Create a draft estimate.
    
    This endpoint:
    1. Creates or retrieves customer by email/phone
    2. Creates or retrieves vehicle by VIN
    3. Recalculates all item totals for consistency
    4. Calculates estimate breakdown
    5. Saves estimate with status='draft'
    6. Generates public token for customer portal
    
    **Returns:** Complete estimate with ID and public token
    """
    service = get_estimate_service(db)
    return service.create_draft_estimate(estimate_data, current_user.id)


@router.get(
    "/{estimate_id}",
    response_model=EstimateResponseSchema,
    summary="Get estimate by ID",
    description="Retrieve a specific estimate by ID with all details."
)
async def get_estimate(
    estimate_id: int,
    current_user: User = Depends(get_current_active_advisor),
    db: Session = Depends(get_db)
):
    """
    Get estimate by ID.
    
    **Authorization:** Only the advisor who created the estimate can view it.
    """
    service = get_estimate_service(db)
    estimate = service.get_estimate(estimate_id)
    
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
    status_filter: Optional[str] = Query(None, description="Filter by status: draft, sent, approved, declined"),
    current_user: User = Depends(get_current_active_advisor),
    db: Session = Depends(get_db)
):
    """
    List all estimates for the current advisor.
    
    **Query Parameters:**
    - status: Optional filter (draft, sent, approved, declined)
    
    **Returns:** List of estimates ordered by creation date (newest first)
    """
    service = get_estimate_service(db)
    return service.get_advisor_estimates(current_user.id, status_filter)


@router.post(
    "/{estimate_id}/send",
    response_model=EstimateResponseSchema,
    summary="Send estimate to customer",
    description="Mark estimate as sent and set expiration date. This triggers SMS notification to customer."
)
async def send_estimate(
    estimate_id: int,
    days_valid: int = Query(7, ge=1, le=30, description="Days until estimate expires"),
    current_user: User = Depends(get_current_active_advisor),
    db: Session = Depends(get_db)
):
    """
    Send estimate to customer.
    
    This endpoint:
    1. Updates estimate status to 'sent'
    2. Sets expiration date (default 7 days)
    3. (Future) Triggers SMS notification via Twilio
    
    **Returns:** Updated estimate with new status and expiration
    """
    service = get_estimate_service(db)
    estimate = service.send_estimate(estimate_id, days_valid)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Estimate with ID {estimate_id} not found"
        )
    
    # TODO: Send SMS notification via Twilio
    # notification_service.send_estimate_sms(estimate.customerInfo.phone, estimate.publicToken)
    
    return estimate
