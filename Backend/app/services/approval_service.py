"""
Customer Approval Portal Service

This service handles the customer-facing approval workflow:
- Generate unique approval links
- Store approval tokens
- Process customer responses
- Track approval outcomes

No login required - customers access via unique token.
"""
from typing import Dict, Optional, List
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import secrets
import uuid

from app.core.config import settings


class ApprovalStatus(Enum):
    """Approval status types"""
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    CALLBACK_REQUESTED = "callback_requested"
    EXPIRED = "expired"


@dataclass
class ApprovalToken:
    """Approval token data"""
    token: str
    estimate_id: str
    customer_name: str
    customer_email: str
    customer_phone: str
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus


class ApprovalService:
    """Service for customer approval portal"""
    
    # In-memory storage for development (replace with database in production)
    _tokens: Dict[str, Dict] = {}
    
    # Token expiry (7 days)
    TOKEN_EXPIRY_DAYS = 7
    
    def __init__(self):
        self.base_url = getattr(settings, 'PUBLIC_URL', 'http://localhost:5173')
    
    def generate_approval_link(
        self,
        estimate_id: str,
        estimate_data: Dict
    ) -> Dict:
        """
        Generate unique approval URL for customer.
        
        Args:
            estimate_id: Internal estimate ID
            estimate_data: Complete estimate data
            
        Returns:
            Approval link data
        """
        # Generate secure token
        token = secrets.token_urlsafe(32)
        
        # Store token with estimate data
        customer = estimate_data.get("customer", {})
        
        token_data = {
            "token": token,
            "estimate_id": estimate_id,
            "customer": {
                "name": customer.get("name", ""),
                "email": customer.get("email", ""),
                "phone": customer.get("phone", "")
            },
            "estimate_data": estimate_data,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=self.TOKEN_EXPIRY_DAYS)).isoformat(),
            "status": ApprovalStatus.PENDING.value,
            "actions": []
        }
        
        self._tokens[token] = token_data
        
        # Generate approval URL
        approval_url = f"{self.base_url}/approve/{token}"
        
        return {
            "success": True,
            "token": token,
            "approval_url": approval_url,
            "expires_at": token_data["expires_at"],
            "sms_message": f"Your estimate from Estimaro is ready! View and approve: {approval_url}",
            "email_subject": "Your Vehicle Estimate is Ready",
            "email_body": f"""
Hello {customer.get('name', 'Valued Customer')},

Your vehicle estimate is ready for review!

Click here to view and approve your estimate:
{approval_url}

If you have any questions, please call us or reply to this email.

This link expires in {self.TOKEN_EXPIRY_DAYS} days.

Thank you for choosing us!
            """.strip()
        }
    
    def get_estimate_by_token(self, token: str) -> Optional[Dict]:
        """
        Retrieve estimate data by approval token.
        
        Args:
            token: Approval token from URL
            
        Returns:
            Estimate data or None if not found/expired
        """
        token_data = self._tokens.get(token)
        
        if not token_data:
            return None
        
        # Check expiry
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        if datetime.utcnow() > expires_at:
            token_data["status"] = ApprovalStatus.EXPIRED.value
            return {
                "success": False,
                "error": "This estimate link has expired",
                "expired": True
            }
        
        return {
            "success": True,
            "token": token,
            "estimate_id": token_data["estimate_id"],
            "customer": token_data["customer"],
            "estimate_data": token_data["estimate_data"],
            "status": token_data["status"],
            "created_at": token_data["created_at"],
            "expires_at": token_data["expires_at"]
        }
    
    def process_approval(
        self,
        token: str,
        action: str,
        notes: str = None
    ) -> Dict:
        """
        Process customer approval/decline action.
        
        Args:
            token: Approval token
            action: "approve", "decline", or "callback"
            notes: Optional customer notes
            
        Returns:
            Processing result
        """
        token_data = self._tokens.get(token)
        
        if not token_data:
            return {
                "success": False,
                "error": "Invalid or expired approval link"
            }
        
        # Check expiry
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        if datetime.utcnow() > expires_at:
            return {
                "success": False,
                "error": "This estimate link has expired"
            }
        
        # Already processed?
        current_status = token_data["status"]
        if current_status != ApprovalStatus.PENDING.value:
            return {
                "success": False,
                "error": f"This estimate has already been {current_status}",
                "status": current_status
            }
        
        # Map action to status
        action_map = {
            "approve": ApprovalStatus.APPROVED,
            "decline": ApprovalStatus.DECLINED,
            "callback": ApprovalStatus.CALLBACK_REQUESTED
        }
        
        new_status = action_map.get(action.lower())
        if not new_status:
            return {
                "success": False,
                "error": f"Invalid action: {action}"
            }
        
        # Update status
        token_data["status"] = new_status.value
        token_data["actions"].append({
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "notes": notes
        })
        
        # Response based on action
        if new_status == ApprovalStatus.APPROVED:
            message = "Thank you! Your repair has been approved. We will contact you shortly to schedule."
            next_step = "schedule"
        elif new_status == ApprovalStatus.DECLINED:
            message = "We understand. Thank you for considering us. Feel free to reach out if you have questions."
            next_step = "closed"
        else:  # callback
            message = "We'll call you back shortly to discuss your estimate."
            next_step = "callback"
        
        return {
            "success": True,
            "action": action,
            "status": new_status.value,
            "message": message,
            "next_step": next_step,
            "estimate_id": token_data["estimate_id"],
            "customer": token_data["customer"],
            "processed_at": datetime.utcnow().isoformat()
        }
    
    def get_approval_stats(self) -> Dict:
        """
        Get approval statistics for dashboard.
        
        Returns:
            Statistics summary
        """
        total = len(self._tokens)
        
        status_counts = {
            ApprovalStatus.PENDING.value: 0,
            ApprovalStatus.APPROVED.value: 0,
            ApprovalStatus.DECLINED.value: 0,
            ApprovalStatus.CALLBACK_REQUESTED.value: 0,
            ApprovalStatus.EXPIRED.value: 0
        }
        
        for token_data in self._tokens.values():
            status = token_data["status"]
            if status in status_counts:
                status_counts[status] += 1
        
        approved = status_counts[ApprovalStatus.APPROVED.value]
        processed = approved + status_counts[ApprovalStatus.DECLINED.value]
        
        return {
            "total_sent": total,
            "pending": status_counts[ApprovalStatus.PENDING.value],
            "approved": approved,
            "declined": status_counts[ApprovalStatus.DECLINED.value],
            "callback_requested": status_counts[ApprovalStatus.CALLBACK_REQUESTED.value],
            "expired": status_counts[ApprovalStatus.EXPIRED.value],
            "approval_rate": f"{(approved / processed * 100):.1f}%" if processed > 0 else "N/A"
        }
    
    def send_notification(
        self,
        token: str,
        method: str = "sms"
    ) -> Dict:
        """
        Send notification to customer (SMS or Email).
        
        Args:
            token: Approval token
            method: "sms" or "email"
            
        Returns:
            Send result (mock for now)
        """
        token_data = self._tokens.get(token)
        
        if not token_data:
            return {
                "success": False,
                "error": "Token not found"
            }
        
        customer = token_data["customer"]
        approval_url = f"{self.base_url}/approve/{token}"
        
        # Mock send - in production, integrate with Twilio/SendGrid
        if method == "sms":
            return {
                "success": True,
                "method": "sms",
                "to": customer.get("phone", ""),
                "message": f"Your estimate is ready! View: {approval_url}",
                "mock": True,
                "status": "sent"
            }
        elif method == "email":
            return {
                "success": True,
                "method": "email",
                "to": customer.get("email", ""),
                "subject": "Your Vehicle Estimate is Ready",
                "mock": True,
                "status": "sent"
            }
        else:
            return {
                "success": False,
                "error": f"Unknown method: {method}"
            }


# Singleton instance
approval_service = ApprovalService()
