from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Vehicle(Base):
    """
    Vehicle model.
    Represents customer vehicles that require service estimates.
    """
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    vin = Column(String(17), unique=True, index=True, nullable=False)
    year = Column(Integer, nullable=True)
    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    trim = Column(String(100), nullable=True)
    engine = Column(String(100), nullable=True)
    mileage = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    customer = relationship("Customer", back_populates="vehicles")
    estimates = relationship("Estimate", back_populates="vehicle", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Vehicle(id={self.id}, vin='{self.vin}', {self.year} {self.make} {self.model})>"
    
    @property
    def display_name(self):
        """Return formatted vehicle name."""
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim]
        return " ".join(filter(None, parts))
