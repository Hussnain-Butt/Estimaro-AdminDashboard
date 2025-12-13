"""
Customer Approval Portal API Routes

Public endpoints for customer approval workflow.
No authentication required - accessed via unique token.
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional

from app.services.approval_service import approval_service

router = APIRouter()


class GenerateApprovalLinkRequest(BaseModel):
    """Request to generate approval link"""
    estimate_id: str = Field(..., description="Internal estimate ID")
    estimate_data: dict = Field(..., description="Complete estimate data")


class ProcessApprovalRequest(BaseModel):
    """Request to process customer approval action"""
    action: str = Field(..., description="approve, decline, or callback")
    notes: Optional[str] = Field(None, description="Optional customer notes")


@router.post(
    "/generate-link",
    summary="Generate approval link",
    description="Generate a unique approval URL to send to customer"
)
async def generate_approval_link(request: GenerateApprovalLinkRequest):
    """
    Generate unique approval link for customer.
    
    Returns:
    - Approval URL
    - SMS message template
    - Email template
    - Expiration date
    """
    try:
        result = approval_service.generate_approval_link(
            estimate_id=request.estimate_id,
            estimate_data=request.estimate_data
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate approval link: {str(e)}"
        )


@router.get(
    "/view/{token}",
    summary="View estimate by token",
    description="Customer-facing: View estimate details via approval token"
)
async def view_estimate(token: str):
    """
    View estimate by approval token.
    
    This is the public endpoint customers access
    when clicking the approval link.
    """
    result = approval_service.get_estimate_by_token(token)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estimate not found or link has expired"
        )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=result.get("error", "Link has expired")
        )
    
    return result


@router.post(
    "/action/{token}",
    summary="Process approval action",
    description="Customer-facing: Approve, decline, or request callback"
)
async def process_approval(token: str, request: ProcessApprovalRequest):
    """
    Process customer's approval action.
    
    Actions:
    - approve: Customer approves the estimate
    - decline: Customer declines the estimate
    - callback: Customer requests a callback
    """
    result = approval_service.process_approval(
        token=token,
        action=request.action,
        notes=request.notes
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to process action")
        )
    
    return result


@router.get(
    "/stats",
    summary="Get approval statistics",
    description="Dashboard: Get approval rate statistics"
)
async def get_approval_stats():
    """Get approval statistics for dashboard."""
    return approval_service.get_approval_stats()


class SendNotificationRequest(BaseModel):
    """Request to send notification"""
    token: str = Field(..., description="Approval token")
    method: str = Field("sms", description="sms or email")


@router.post(
    "/send-notification",
    summary="Send notification to customer",
    description="Send SMS or email notification with approval link"
)
async def send_notification(request: SendNotificationRequest):
    """
    Send notification to customer.
    
    Methods:
    - sms: Send SMS with approval link
    - email: Send email with approval link
    """
    result = approval_service.send_notification(
        token=request.token,
        method=request.method
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to send notification")
        )
    
    return result
