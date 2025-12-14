from pydantic import BaseModel, Field, BeforeValidator
from decimal import Decimal
from typing import Optional, Annotated, Any
import enum
import uuid

def coerce_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        # Handle Decimal128 and other types by converting to string first
        return float(str(v))
    except (ValueError, TypeError):
        return 0.0

class ItemType(str, enum.Enum):
    """Estimate item type enumeration."""
    LABOR = "labor"
    PART = "part"

class EstimateItem(BaseModel):
    """
    Estimate Item model.
    Embedded in Estimate document.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    item_type: str = "part" # Fallback to string to avoid Enum validation errors
    description: str = "Unknown Item"
    
    # Common fields
    quantity: Annotated[float, BeforeValidator(coerce_float)] = 1.0
    unit_price: Annotated[float, BeforeValidator(coerce_float)] = 0.0
    markup_percentage: Optional[Annotated[float, BeforeValidator(coerce_float)]] = 0.0
    total: Annotated[float, BeforeValidator(coerce_float)] = 0.0
    
    # Part-specific fields
    vendor_name: Optional[str] = None
    part_number: Optional[str] = None
    
    # Labor-specific fields
    labor_hours: Optional[Annotated[float, BeforeValidator(coerce_float)]] = None
    
    @property
    def is_labor(self):
        return self.item_type == "labor"
    
    @property
    def is_part(self):
        return self.item_type == "part"

