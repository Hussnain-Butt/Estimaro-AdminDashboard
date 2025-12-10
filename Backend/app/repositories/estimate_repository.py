"""
Estimate Repository - Data Access Layer

Handles all database operations for estimates, following the Repository Pattern.
Separates data access logic from business logic.
"""
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from decimal import Decimal
import uuid

from app.models.estimate import Estimate, EstimateStatus
from app.models.estimate_item import EstimateItem, ItemType
from app.models.vehicle import Vehicle
from app.models.customer import Customer
from app.schemas.estimate import (
    EstimateCreateSchema,
    LaborItemSchema,
    PartItemSchema
)


class EstimateRepository:
    """Repository for estimate database operations"""
    
    def __init__(self, db: Session):
        """
        Initialize repository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def create_estimate(
        self,
        estimate_data: EstimateCreateSchema,
        advisor_id: int,
        breakdown: dict
    ) -> Estimate:
        """
        Create a new estimate with all related data.
        
        This method:
        1. Creates or retrieves customer
        2. Creates or retrieves vehicle
        3. Creates estimate
        4. Creates estimate items (labor and parts)
        
        Args:
            estimate_data: Estimate creation data
            advisor_id: ID of the advisor creating the estimate
            breakdown: Calculation breakdown (subtotal, tax, total)
            
        Returns:
            Created estimate with all relationships loaded
        """
        # Step 1: Create or get customer
        customer = self._get_or_create_customer(estimate_data.customerInfo)
        
        # Step 2: Create or get vehicle
        vehicle = self._get_or_create_vehicle(
            estimate_data.vehicleInfo,
            customer.id
        )
        
        # Step 3: Create estimate
        estimate = Estimate(
            vehicle_id=vehicle.id,
            advisor_id=advisor_id,
            service_request_text=estimate_data.serviceRequest,
            status=EstimateStatus.DRAFT,
            subtotal=Decimal(str(breakdown['subtotal'])),
            tax=Decimal(str(breakdown['taxAmount'])),
            total=Decimal(str(breakdown['total'])),
            public_token=str(uuid.uuid4())
        )
        
        self.db.add(estimate)
        self.db.flush()  # Get estimate ID without committing
        
        # Step 4: Create estimate items
        self._create_estimate_items(
            estimate.id,
            estimate_data.laborItems,
            estimate_data.partsItems
        )
        
        self.db.commit()
        self.db.refresh(estimate)
        
        # Load all relationships
        return self.get_by_id(estimate.id)
    
    def get_by_id(self, estimate_id: int) -> Optional[Estimate]:
        """
        Get estimate by ID with all relationships loaded.
        
        Args:
            estimate_id: Estimate ID
            
        Returns:
            Estimate with relationships or None
        """
        return self.db.query(Estimate).options(
            joinedload(Estimate.vehicle).joinedload(Vehicle.customer),
            joinedload(Estimate.advisor),
            joinedload(Estimate.items)
        ).filter(Estimate.id == estimate_id).first()
    
    def get_by_token(self, public_token: str) -> Optional[Estimate]:
        """
        Get estimate by public token (for customer portal).
        
        Args:
            public_token: Public UUID token
            
        Returns:
            Estimate or None
        """
        return self.db.query(Estimate).options(
            joinedload(Estimate.vehicle).joinedload(Vehicle.customer),
            joinedload(Estimate.items)
        ).filter(Estimate.public_token == public_token).first()
    
    def get_by_advisor(
        self,
        advisor_id: int,
        status: Optional[EstimateStatus] = None,
        limit: int = 50
    ) -> List[Estimate]:
        """
        Get estimates by advisor with optional status filter.
        
        Args:
            advisor_id: Advisor ID
            status: Optional status filter
            limit: Maximum number of results
            
        Returns:
            List of estimates
        """
        query = self.db.query(Estimate).options(
            joinedload(Estimate.vehicle).joinedload(Vehicle.customer),
            joinedload(Estimate.items)
        ).filter(Estimate.advisor_id == advisor_id)
        
        if status:
            query = query.filter(Estimate.status == status)
        
        return query.order_by(desc(Estimate.created_at)).limit(limit).all()
    
    def update_status(
        self,
        estimate_id: int,
        status: EstimateStatus
    ) -> Optional[Estimate]:
        """
        Update estimate status.
        
        Args:
            estimate_id: Estimate ID
            status: New status
            
        Returns:
            Updated estimate or None
        """
        estimate = self.get_by_id(estimate_id)
        if not estimate:
            return None
        
        estimate.status = status
        self.db.commit()
        self.db.refresh(estimate)
        
        return estimate
    
    def set_expiration(
        self,
        estimate_id: int,
        days: int = 7
    ) -> Optional[Estimate]:
        """
        Set estimate expiration date.
        
        Args:
            estimate_id: Estimate ID
            days: Days until expiration
            
        Returns:
            Updated estimate or None
        """
        estimate = self.get_by_id(estimate_id)
        if not estimate:
            return None
        
        estimate.set_expiration(days)
        self.db.commit()
        self.db.refresh(estimate)
        
        return estimate
    
    # ========================================================================
    # Private Helper Methods
    # ========================================================================
    
    def _get_or_create_customer(self, customer_info) -> Customer:
        """Get existing customer or create new one."""
        # Try to find by email or phone
        customer = None
        
        if customer_info.email:
            customer = self.db.query(Customer).filter(
                Customer.email == customer_info.email
            ).first()
        
        if not customer and customer_info.phone:
            customer = self.db.query(Customer).filter(
                Customer.phone == customer_info.phone
            ).first()
        
        if not customer:
            customer = Customer(
                first_name=customer_info.firstName,
                last_name=customer_info.lastName,
                email=customer_info.email,
                phone=customer_info.phone
            )
            self.db.add(customer)
            self.db.flush()
        
        return customer
    
    def _get_or_create_vehicle(self, vehicle_info, customer_id: int) -> Vehicle:
        """Get existing vehicle or create new one."""
        # Try to find by VIN
        vehicle = self.db.query(Vehicle).filter(
            Vehicle.vin == vehicle_info.vin
        ).first()
        
        if not vehicle:
            vehicle = Vehicle(
                customer_id=customer_id,
                vin=vehicle_info.vin,
                year=vehicle_info.year,
                make=vehicle_info.make,
                model=vehicle_info.model,
                trim=vehicle_info.trim,
                engine=vehicle_info.engine,
                mileage=vehicle_info.mileage
            )
            self.db.add(vehicle)
            self.db.flush()
        else:
            # Update vehicle info if changed
            vehicle.customer_id = customer_id
            if vehicle_info.year:
                vehicle.year = vehicle_info.year
            if vehicle_info.make:
                vehicle.make = vehicle_info.make
            if vehicle_info.model:
                vehicle.model = vehicle_info.model
            if vehicle_info.trim:
                vehicle.trim = vehicle_info.trim
            if vehicle_info.engine:
                vehicle.engine = vehicle_info.engine
            if vehicle_info.mileage:
                vehicle.mileage = vehicle_info.mileage
        
        return vehicle
    
    def _create_estimate_items(
        self,
        estimate_id: int,
        labor_items: List[LaborItemSchema],
        parts_items: List[PartItemSchema]
    ):
        """Create estimate items (labor and parts)."""
        # Create labor items
        for labor in labor_items:
            item = EstimateItem(
                estimate_id=estimate_id,
                item_type=ItemType.LABOR,
                description=labor.description,
                quantity=Decimal("1"),  # Labor is always quantity 1
                unit_price=Decimal(str(labor.rate)),
                labor_hours=Decimal(str(labor.hours)),
                total=Decimal(str(labor.total))
            )
            self.db.add(item)
        
        # Create parts items
        for part in parts_items:
            item = EstimateItem(
                estimate_id=estimate_id,
                item_type=ItemType.PART,
                description=part.description,
                quantity=Decimal(str(part.quantity)),
                unit_price=Decimal(str(part.cost)),
                markup_percentage=Decimal(str(part.markup)),
                total=Decimal(str(part.total)),
                vendor_name=part.vendor,
                part_number=part.partNumber
            )
            self.db.add(item)
