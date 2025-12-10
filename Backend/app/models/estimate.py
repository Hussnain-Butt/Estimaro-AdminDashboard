from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Numeric, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import enum
import uuid
from app.core.database import Base


class EstimateStatus(str, enum.Enum):
    """Estimate status enumeration."""
    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    DECLINED = "declined"


class Estimate(Base):
    """
    Estimate model.
    Represents a service estimate for a vehicle.
    """
    __tablename__ = "estimates"
    
    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    advisor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    service_request_text = Column(Text, nullable=True)
    status = Column(SQLEnum(EstimateStatus), default=EstimateStatus.DRAFT, nullable=False, index=True)
    
    # Financial fields (using Numeric for precision)
    subtotal = Column(Numeric(10, 2), default=0.00, nullable=False)
    tax = Column(Numeric(10, 2), default=0.00, nullable=False)
    total = Column(Numeric(10, 2), default=0.00, nullable=False)
    
    # Customer portal access
    public_token = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # For customer portal link expiration
    
    # External system integration
    tekmetric_id = Column(String(100), nullable=True, index=True)
    
    # Relationships
    vehicle = relationship("Vehicle", back_populates="estimates")
    advisor = relationship("User", back_populates="estimates")
    items = relationship("EstimateItem", back_populates="estimate", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Estimate(id={self.id}, status='{self.status}', total={self.total})>"
    
    @property
    def is_expired(self):
        """Check if estimate has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def set_expiration(self, days: int = 7):
        """Set expiration date from now."""
        self.expires_at = datetime.utcnow() + timedelta(days=days)
