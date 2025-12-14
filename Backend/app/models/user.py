from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
import enum

class UserRole(str, enum.Enum):
    """User role enumeration."""
    ADVISOR = "advisor"
    ADMIN = "admin"

class User(Document):
    """
    User (Advisor) model.
    Represents shop advisors who create estimates.
    """
    email: str = Indexed(unique=True)
    hashed_password: str
    full_name: str
    shop_name: str = "My Auto Shop"  # Default if not provided
    role: UserRole = UserRole.ADVISOR
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "users"

