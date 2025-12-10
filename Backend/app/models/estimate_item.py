from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class ItemType(str, enum.Enum):
    """Estimate item type enumeration."""
    LABOR = "labor"
    PART = "part"


class EstimateItem(Base):
    """
    Estimate Item model.
    Represents individual labor or part items in an estimate.
    """
    __tablename__ = "estimate_items"
    
    id = Column(Integer, primary_key=True, index=True)
    estimate_id = Column(Integer, ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(SQLEnum(ItemType), nullable=False)
    description = Column(String(500), nullable=False)
    
    # Common fields
    quantity = Column(Numeric(10, 2), default=1.00, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    markup_percentage = Column(Numeric(5, 2), default=0.00, nullable=True)  # For parts
    total = Column(Numeric(10, 2), nullable=False)
    
    # Part-specific fields
    vendor_name = Column(String(100), nullable=True)
    part_number = Column(String(100), nullable=True)
    
    # Labor-specific fields
    labor_hours = Column(Numeric(5, 2), nullable=True)
    
    # Relationships
    estimate = relationship("Estimate", back_populates="items")
    
    def __repr__(self):
        return f"<EstimateItem(id={self.id}, type='{self.item_type}', description='{self.description[:30]}...', total={self.total})>"
    
    @property
    def is_labor(self):
        """Check if item is labor type."""
        return self.item_type == ItemType.LABOR
    
    @property
    def is_part(self):
        """Check if item is part type."""
        return self.item_type == ItemType.PART
