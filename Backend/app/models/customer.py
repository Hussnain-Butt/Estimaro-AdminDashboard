from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
from typing import Optional

class Customer(Document):
    """
    Customer model.
    Represents customers who own vehicles and receive estimates.
    """
    first_name: str
    last_name: str
    email: Optional[str] = Indexed(default=None)
    phone: str = Indexed()
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "customers"
    
    @property
    def full_name(self):
        """Return customer's full name."""
        return f"{self.first_name} {self.last_name}"
    
    async def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        await super().save(*args, **kwargs)

