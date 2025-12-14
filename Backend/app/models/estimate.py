from beanie import Document, Indexed
from pydantic import Field, BeforeValidator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Annotated, Any
import enum
import uuid
from app.models.estimate_item import EstimateItem

def coerce_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        # Handle Decimal128 and other types by converting to string first
        return float(str(v))
    except (ValueError, TypeError):
        return 0.0

class EstimateStatus(str, enum.Enum):
    """Estimate status enumeration."""
    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    DECLINED = "declined"

class Estimate(Document):
    """
    Estimate model.
    Represents a service estimate for a vehicle.
    """
    # References to other documents (stored as strings/ObjectIds)
    vehicle_id: Optional[str] = None  # PydanticObjectId can be used, keeping simple for now
    advisor_id: Optional[str] = None
    
    service_request_text: Optional[str] = None
    status: EstimateStatus = EstimateStatus.DRAFT
    
    # Financial fields
    subtotal: Annotated[float, BeforeValidator(coerce_float)] = 0.0
    tax: Annotated[float, BeforeValidator(coerce_float)] = 0.0
    total: Annotated[float, BeforeValidator(coerce_float)] = 0.0
    
    # Customer portal access
    public_token: str = Indexed(unique=True, default_factory=lambda: str(uuid.uuid4()))
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # External system integration
    tekmetric_id: Optional[str] = None
    
    # Embedded Items
    items: List[EstimateItem] = []
    
    # Runtime fields (not stored in DB)
    vehicle: Optional[Any] = Field(None, exclude=True)

    
    class Settings:
        name = "estimates"
        use_state_management = True
    
    @property
    def is_expired(self):
        """Check if estimate has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def set_expiration(self, days: int = 7):
        """Set expiration date from now."""
        self.expires_at = datetime.utcnow() + timedelta(days=days)
        
    async def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        await super().save(*args, **kwargs)
