"""
Public API Routes (No Authentication Required)

These endpoints are accessible via public tokens for customer portal access.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.schemas.estimate import EstimateResponseSchema
from app.services.estimate_service import get_estimate_service

router = APIRouter()


class CustomerResponseSchema(BaseModel):
    """Customer response to estimate"""
    action: str  # "approve" or "decline"
    customerNotes: str = ""


@router.get(
    "/estimates/{token}",
    response_model=EstimateResponseSchema,
    summary="Get estimate by public token",
    description="Customer portal endpoint to view estimate details using public token from SMS link."
)
async def get_estimate_by_token(
    token: str
):
    """
    Get estimate by public token (customer portal).
    
    **No authentication required** - token is the security mechanism.
    """
    service = get_estimate_service()
    estimate = await service.get_estimate_by_token(token)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate not found or has expired"
        )
    
    return estimate


@router.post(
    "/estimates/{token}/respond",
    summary="Customer response to estimate",
    description="Customer approves or declines the estimate via public portal."
)
async def respond_to_estimate(
    token: str,
    response: CustomerResponseSchema
):
    """
    Customer responds to estimate (approve/decline).
    
    **Actions:**
    - approve: Updates status to 'approved'
    - decline: Updates status to 'declined'
    """
    service = get_estimate_service()
    estimate = await service.get_estimate_by_token(token)
    
    if not estimate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate not found or has expired"
        )
    
    # Validate action
    if response.action not in ["approve", "decline"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be 'approve' or 'decline'"
        )
    
    # Update status based on action
    from app.models.estimate import EstimateStatus
    from app.repositories.estimate_repository import EstimateRepository
    
    repository = EstimateRepository()
    new_status = EstimateStatus.APPROVED if response.action == "approve" else EstimateStatus.DECLINED
    
    # Use estimateId from the retrieved estimate
    await repository.update_status(estimate.estimateId, new_status)
    
    # TODO: Send notification to advisor
    # notification_service.notify_advisor(estimate.advisorId, response)
    
    return {
        "message": f"Estimate {response.action}d successfully",
        "status": new_status.value
    }

