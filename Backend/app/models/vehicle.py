from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
from typing import Optional

class Vehicle(Document):
    """
    Vehicle model.
    Represents customer vehicles that require service estimates.
    """
    vin: str = Indexed(unique=True)
    customer_id: Optional[str] = None  # Reference to Customer Document ID
    
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None
    mileage: Optional[int] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "vehicles"
    
    @property
    def display_name(self):
        """Return formatted vehicle name."""
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim]
        return " ".join(filter(None, parts))

