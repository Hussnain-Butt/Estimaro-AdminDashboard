"""
Estimate Service - Business Logic Layer

Orchestrates estimate operations by coordinating between:
- Calculation Service (for financial calculations)
- Estimate Repository (for database operations)

This is the main service layer that API routes will use.
"""
from typing import Optional, List
from decimal import Decimal

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
    """Service for estimate business logic (Async)"""
    
    def __init__(self):
        """
        Initialize service.
        No database session required for Beanie.
        """
        self.repository = EstimateRepository()
    
    def calculate_estimate(
        self,
        request: CalculationRequestSchema
    ) -> CalculationResponseSchema:
        """
        Calculate estimate totals in real-time (no database save).
        This method remains synchronous as it does no I/O.
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
    
    async def create_draft_estimate(
        self,
        estimate_data: EstimateCreateSchema,
        advisor_id: str
    ) -> EstimateResponseSchema:
        """
        Create a draft estimate and save to database.
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
        estimate = await self.repository.create_estimate(
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
    
    async def get_estimate(self, estimate_id: str) -> Optional[EstimateResponseSchema]:
        """Get estimate by ID."""
        estimate = await self.repository.get_by_id(estimate_id)
        if not estimate:
            return None
        
        return self._estimate_to_response(estimate)
    
    async def get_estimate_by_token(self, public_token: str) -> Optional[EstimateResponseSchema]:
        """Get estimate by public token."""
        estimate = await self.repository.get_by_token(public_token)
        if not estimate:
            return None
        
        # Check if expired
        if estimate.is_expired:
            return None
        
        return self._estimate_to_response(estimate)
    
    async def get_advisor_estimates(
        self,
        advisor_id: str,
        status: Optional[str] = None
    ) -> List[EstimateResponseSchema]:
        """Get all estimates for an advisor."""
        status_enum = EstimateStatus(status) if status else None
        estimates = await self.repository.get_by_advisor(advisor_id, status_enum)
        
        return [self._estimate_to_response(est) for est in estimates]
    
    async def send_estimate(self, estimate_id: str, days_valid: int = 7) -> Optional[EstimateResponseSchema]:
        """Send estimate to customer."""
        # Update status to 'sent'
        estimate = await self.repository.update_status(estimate_id, EstimateStatus.SENT)
        if not estimate:
            return None
        
        # Set expiration
        estimate = await self.repository.set_expiration(estimate_id, days_valid)
        
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
                    hours=float(item.labor_hours or 0),
                    rate=float(item.unit_price or 0),
                    total=float(item.total or 0)
                ))
            elif item.is_part:
                parts_items.append(PartItemSchema(
                    id=str(item.id),
                    description=item.description,
                    partNumber=item.part_number,
                    quantity=float(item.quantity or 0),
                    cost=float(item.unit_price or 0),
                    markup=float(item.markup_percentage or 0),
                    total=float(item.total or 0),
                    vendor=item.vendor_name
                ))
        
        # Build breakdown
        labor_total_val = sum(item.total for item in labor_items)
        parts_total_val = sum(item.total for item in parts_items)
        
        breakdown = CalculationBreakdownSchema(
            laborTotal=float(labor_total_val),
            partsTotal=float(parts_total_val),
            subtotal=float(estimate.subtotal or 0),
            taxAmount=float(estimate.tax or 0),
            total=float(estimate.total or 0)
        )
        
        # Build vehicle info & Customer info
        # Using getattr to access forcefully attached relationships
        # This bypasses Pydantic model dictionary lookups which might miss the extra fields
        vehicle_info = None
        customer_info = None
        
        vehicle = getattr(estimate, 'vehicle', None)
        
        if vehicle:
            vehicle_info = VehicleInfoSchema(
                vin=vehicle.vin or "UNKNOWN",
                year=vehicle.year,
                make=vehicle.make,
                model=vehicle.model,
                trim=vehicle.trim,
                engine=vehicle.engine,
                mileage=vehicle.mileage
            )
            
            # Access customer from the vehicle object
            customer = getattr(vehicle, 'customer', None)
            
            if customer:
                customer_info = CustomerInfoSchema(
                    firstName=customer.first_name or "Unknown",
                    lastName=customer.last_name or "",
                    email=customer.email,
                    phone=customer.phone or ""
                )
        
        # Fallbacks if objects are missing
        if not vehicle_info:
            vehicle_info = VehicleInfoSchema(
                vin="UNKNOWN",
                year=None,
                make="Unknown",
                model="Vehicle", 
                trim=None,
                engine=None,
                mileage=None
            )
            
        if not customer_info:
            customer_info = CustomerInfoSchema(
                firstName="Unknown",
                lastName="Customer",
                email=None,
                phone="000-000-0000"
            )
        
        return EstimateResponseSchema(
            estimateId=str(estimate.id),
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


def get_estimate_service() -> EstimateService:
    """
    Factory function to create EstimateService instance.
    """
    return EstimateService()