"""
Estimate Service - Business Logic Layer

Orchestrates estimate operations by coordinating between:
- Calculation Service (for financial calculations)
- Estimate Repository (for database operations)

This is the main service layer that API routes will use.
"""
from typing import Optional, List
from decimal import Decimal
from sqlalchemy.orm import Session

from app.schemas.estimate import (
    EstimateCreateSchema,
    CalculationRequestSchema,
    CalculationResponseSchema,
    EstimateResponseSchema,
    CalculationBreakdownSchema,
    VehicleInfoSchema,
    CustomerInfoSchema,
    LaborItemSchema,
    PartItemSchema
)
from app.services.calculation_service import calculation_service
from app.repositories.estimate_repository import EstimateRepository
from app.models.estimate import Estimate, EstimateStatus
from app.models.estimate_item import ItemType


class EstimateService:
    """Service for estimate business logic"""
    
    def __init__(self, db: Session):
        """
        Initialize service with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.repository = EstimateRepository(db)
    
    def calculate_estimate(
        self,
        request: CalculationRequestSchema
    ) -> CalculationResponseSchema:
        """
        Calculate estimate totals in real-time (no database save).
        
        This is used for the frontend real-time calculation as user
        adds/modifies labor and parts items.
        
        Args:
            request: Calculation request with labor/parts items
            
        Returns:
            Calculation response with breakdown
        """
        # Use provided tax rate or default
        tax_rate = request.taxRate or Decimal(str(calculation_service.tax_rate))
        
        # Calculate breakdown
        breakdown = calculation_service.calculate_estimate(
            labor_items=request.laborItems,
            parts_items=request.partsItems,
            tax_rate=tax_rate
        )
        
        return CalculationResponseSchema(
            breakdown=breakdown,
            taxRate=tax_rate
        )
    
    def create_draft_estimate(
        self,
        estimate_data: EstimateCreateSchema,
        advisor_id: int
    ) -> EstimateResponseSchema:
        """
        Create a draft estimate and save to database.
        
        This method:
        1. Recalculates item totals to ensure consistency
        2. Calculates estimate breakdown
        3. Creates estimate in database
        4. Returns formatted response
        
        Args:
            estimate_data: Estimate creation data
            advisor_id: ID of the advisor creating the estimate
            
        Returns:
            Created estimate response
        """
        # Recalculate item totals for consistency
        recalculated = calculation_service.recalculate_item_totals(
            labor_items=estimate_data.laborItems,
            parts_items=estimate_data.partsItems
        )
        
        # Update estimate data with recalculated items
        estimate_data.laborItems = recalculated['laborItems']
        estimate_data.partsItems = recalculated['partsItems']
        
        # Calculate breakdown
        breakdown = calculation_service.calculate_estimate(
            labor_items=estimate_data.laborItems,
            parts_items=estimate_data.partsItems
        )
        
        # Create estimate in database
        estimate = self.repository.create_estimate(
            estimate_data=estimate_data,
            advisor_id=advisor_id,
            breakdown={
                'subtotal': breakdown.subtotal,
                'taxAmount': breakdown.taxAmount,
                'total': breakdown.total
            }
        )
        
        # Convert to response schema
        return self._estimate_to_response(estimate)
    
    def get_estimate(self, estimate_id: int) -> Optional[EstimateResponseSchema]:
        """
        Get estimate by ID.
        
        Args:
            estimate_id: Estimate ID
            
        Returns:
            Estimate response or None
        """
        estimate = self.repository.get_by_id(estimate_id)
        if not estimate:
            return None
        
        return self._estimate_to_response(estimate)
    
    def get_estimate_by_token(self, public_token: str) -> Optional[EstimateResponseSchema]:
        """
        Get estimate by public token (for customer portal).
        
        Args:
            public_token: Public UUID token
            
        Returns:
            Estimate response or None
        """
        estimate = self.repository.get_by_token(public_token)
        if not estimate:
            return None
        
        # Check if expired
        if estimate.is_expired:
            return None
        
        return self._estimate_to_response(estimate)
    
    def get_advisor_estimates(
        self,
        advisor_id: int,
        status: Optional[str] = None
    ) -> List[EstimateResponseSchema]:
        """
        Get all estimates for an advisor.
        
        Args:
            advisor_id: Advisor ID
            status: Optional status filter
            
        Returns:
            List of estimate responses
        """
        status_enum = EstimateStatus(status) if status else None
        estimates = self.repository.get_by_advisor(advisor_id, status_enum)
        
        return [self._estimate_to_response(est) for est in estimates]
    
    def send_estimate(self, estimate_id: int, days_valid: int = 7) -> Optional[EstimateResponseSchema]:
        """
        Send estimate to customer (update status and set expiration).
        
        Args:
            estimate_id: Estimate ID
            days_valid: Days until expiration
            
        Returns:
            Updated estimate or None
        """
        # Update status to 'sent'
        estimate = self.repository.update_status(estimate_id, EstimateStatus.SENT)
        if not estimate:
            return None
        
        # Set expiration
        estimate = self.repository.set_expiration(estimate_id, days_valid)
        
        return self._estimate_to_response(estimate)
    
    # ========================================================================
    # Private Helper Methods
    # ========================================================================
    
    def _estimate_to_response(self, estimate: Estimate) -> EstimateResponseSchema:
        """Convert database estimate to response schema."""
        # Extract labor and parts items
        labor_items = []
        parts_items = []
        
        for item in estimate.items:
            if item.is_labor:
                labor_items.append(LaborItemSchema(
                    id=str(item.id),
                    description=item.description,
                    hours=item.labor_hours,
                    rate=item.unit_price,
                    total=item.total
                ))
            elif item.is_part:
                parts_items.append(PartItemSchema(
                    id=str(item.id),
                    description=item.description,
                    partNumber=item.part_number,
                    quantity=item.quantity,
                    cost=item.unit_price,
                    markup=item.markup_percentage or Decimal("0"),
                    total=item.total,
                    vendor=item.vendor_name
                ))
        
        # Build breakdown
        breakdown = CalculationBreakdownSchema(
            laborTotal=sum(item.total for item in labor_items) if labor_items else Decimal("0"),
            partsTotal=sum(item.total for item in parts_items) if parts_items else Decimal("0"),
            subtotal=estimate.subtotal,
            taxAmount=estimate.tax,
            total=estimate.total
        )
        
        # Build vehicle info
        vehicle = estimate.vehicle
        vehicle_info = VehicleInfoSchema(
            vin=vehicle.vin,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            engine=vehicle.engine,
            mileage=vehicle.mileage
        )
        
        # Build customer info
        customer = vehicle.customer
        customer_info = CustomerInfoSchema(
            firstName=customer.first_name,
            lastName=customer.last_name,
            email=customer.email,
            phone=customer.phone
        )
        
        return EstimateResponseSchema(
            estimateId=estimate.id,
            status=estimate.status.value,
            publicToken=estimate.public_token,
            vehicleInfo=vehicle_info,
            customerInfo=customer_info,
            serviceRequest=estimate.service_request_text,
            laborItems=labor_items,
            partsItems=parts_items,
            breakdown=breakdown,
            createdAt=estimate.created_at,
            updatedAt=estimate.updated_at,
            expiresAt=estimate.expires_at
        )


def get_estimate_service(db: Session) -> EstimateService:
    """
    Factory function to create EstimateService instance.
    
    Args:
        db: Database session
        
    Returns:
        EstimateService instance
    """
    return EstimateService(db)
