from typing import Optional, List, Dict
from decimal import Decimal
import uuid
import logging
from beanie import PydanticObjectId

# Models
from app.models.estimate import Estimate, EstimateStatus
from app.models.estimate_item import EstimateItem, ItemType
from app.models.vehicle import Vehicle
from app.models.customer import Customer

# Schemas
from app.schemas.estimate import (
    EstimateCreateSchema,
    LaborItemSchema,
    PartItemSchema
)

# Logger setup
logger = logging.getLogger(__name__)

class EstimateRepository:
    """
    Repository for estimate database operations (MongoDB/Beanie).
    Handles data persistence and relationship management.
    """
    
    def __init__(self, db=None):
        pass
    
    async def create_estimate(
        self,
        estimate_data: EstimateCreateSchema,
        advisor_id: str,
        breakdown: Optional[Dict] = None
    ) -> Estimate:
        """
        Create a new estimate with all related data.
        """
        try:
            # Step 1: Create or get customer
            customer = await self._get_or_create_customer(estimate_data.customerInfo)
            
            # Step 2: Create or get vehicle
            vehicle = await self._get_or_create_vehicle(
                estimate_data.vehicleInfo,
                str(customer.id)
            )
            
            # Step 3: Create items list
            items = self._create_estimate_items(
                estimate_data.laborItems,
                estimate_data.partsItems
            )
            
            # Safe breakdown handling
            if breakdown is None:
                breakdown = {}
                calc_subtotal = sum(item.total for item in items)
                breakdown['subtotal'] = calc_subtotal
                breakdown['taxAmount'] = 0.0
                breakdown['total'] = calc_subtotal

            # Step 4: Create estimate
            estimate = Estimate(
                vehicle_id=str(vehicle.id),
                advisor_id=str(advisor_id) if advisor_id else None,
                service_request_text=estimate_data.serviceRequest,
                status=EstimateStatus.DRAFT,
                subtotal=float(breakdown.get('subtotal', 0.0)),
                tax=float(breakdown.get('taxAmount', 0.0)),
                total=float(breakdown.get('total', 0.0)),
                public_token=str(uuid.uuid4()),
                items=items
            )
            
            await estimate.insert()
            
            # FORCE ATTACH objects for return (Bypass Pydantic validation)
            object.__setattr__(estimate, 'vehicle', vehicle)
            object.__setattr__(vehicle, 'customer', customer)
            
            return estimate

        except Exception as e:
            logger.error(f"Failed to create estimate: {str(e)}")
            raise e
    
    async def get_by_id(self, estimate_id: str) -> Optional[Estimate]:
        """Get estimate by ID with relationships."""
        try:
            if not PydanticObjectId.is_valid(estimate_id):
                return None
            estimate = await Estimate.get(PydanticObjectId(estimate_id))
        except Exception as e:
            logger.error(f"Error fetching estimate by ID {estimate_id}: {e}")
            return None
            
        if not estimate:
            return None
            
        await self._populate_relations(estimate)
        return estimate
    
    async def get_by_token(self, public_token: str) -> Optional[Estimate]:
        """Get estimate by public token."""
        try:
            estimate = await Estimate.find_one(Estimate.public_token == public_token)
            if not estimate:
                return None
                
            await self._populate_relations(estimate)
            return estimate
        except Exception:
            return None
    
    async def get_by_advisor(
        self,
        advisor_id: str,
        status: Optional[EstimateStatus] = None,
        limit: int = 50
    ) -> List[Estimate]:
        """Get estimates by advisor."""
        try:
            if advisor_id == "system":
                 query = Estimate.find_all()
            else:
                 query = Estimate.find(Estimate.advisor_id == str(advisor_id))
            
            if status:
                query = query.find(Estimate.status == status)
                
            estimates = await query.sort("-created_at").limit(limit).to_list()
            
            # Populate relations for each estimate
            for est in estimates:
                await self._populate_relations(est)
                
            return estimates
        except Exception as e:
            logger.error(f"Error getting estimates for advisor {advisor_id}: {e}")
            return []
    
    async def update_status(
        self,
        estimate_id: str,
        status: EstimateStatus
    ) -> Optional[Estimate]:
        """Update estimate status."""
        estimate = await self.get_by_id(estimate_id)
        if not estimate:
            return None
        
        estimate.status = status
        await estimate.save()
        return estimate
    
    async def set_expiration(
        self,
        estimate_id: str,
        days: int = 7
    ) -> Optional[Estimate]:
        """Set estimate expiration date."""
        estimate = await self.get_by_id(estimate_id)
        if not estimate:
            return None
        
        estimate.set_expiration(days)
        await estimate.save()
        return estimate
        
    async def _populate_relations(self, estimate: Estimate):
        """
        Manually fetch and attach vehicle and customer.
        Uses object.__setattr__ to bypass Pydantic model restrictions.
        """
        if not estimate.vehicle_id:
            return

        try:
            vehicle = None
            
            # 1. Fetch Vehicle (Try ObjectId first, then string)
            if PydanticObjectId.is_valid(estimate.vehicle_id):
                vehicle = await Vehicle.get(PydanticObjectId(estimate.vehicle_id))
            
            if not vehicle:
                # Fallback: Try string lookup
                vehicle = await Vehicle.get(estimate.vehicle_id)
                
            if vehicle:
                # FORCE ATTACH vehicle to estimate
                object.__setattr__(estimate, 'vehicle', vehicle)
                
                # 2. Fetch Customer if Vehicle exists
                if vehicle.customer_id:
                    customer = None
                    cust_id = vehicle.customer_id
                    
                    # Try converting to PydanticObjectId
                    if PydanticObjectId.is_valid(cust_id):
                        customer = await Customer.get(PydanticObjectId(cust_id))
                    
                    # Fallback: String lookup
                    if not customer:
                        customer = await Customer.get(cust_id)
                        
                    if customer:
                        # FORCE ATTACH customer to vehicle (Critical Fix)
                        object.__setattr__(vehicle, 'customer', customer)
                        print(f"DEBUG: Linked Customer {customer.first_name} to Vehicle {vehicle.vin}")
                    else:
                        print(f"DEBUG: Customer ID {cust_id} found in vehicle but Customer not found in DB.")
                else:
                    print(f"DEBUG: Vehicle {vehicle.id} has NO customer_id linked.")
            else:
                print(f"DEBUG: Vehicle ID {estimate.vehicle_id} not found.")

        except Exception as e:
            # Ensure we don't crash, just log and continue
            print(f"DEBUG: Exception in _populate_relations: {e}")
            pass
    
    async def _get_or_create_customer(self, customer_info) -> Customer:
        """Get existing customer or create new one."""
        customer = None
        
        # Normalize inputs
        email = customer_info.email.strip().lower() if customer_info.email else None
        phone = customer_info.phone.strip() if customer_info.phone else None
        first_name = customer_info.firstName.strip() if customer_info.firstName else "Unknown"
        last_name = customer_info.lastName.strip() if customer_info.lastName else ""
        
        # Try finding by Email
        if email:
            customer = await Customer.find_one(Customer.email == email)
        
        # Try finding by Phone
        if not customer and phone:
            customer = await Customer.find_one(Customer.phone == phone)
        
        # Create if not found
        if not customer:
            customer = Customer(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone
            )
            await customer.insert()
        else:
            # Update info if valid names provided and previous were placeholders
            if customer.first_name == "Unknown" and first_name != "Unknown":
                customer.first_name = first_name
                customer.last_name = last_name
                await customer.save()
        
        return customer
    
    async def _get_or_create_vehicle(self, vehicle_info, customer_id: str) -> Vehicle:
        """Get existing vehicle or create new one."""
        search_vin = vehicle_info.vin.strip().upper() if vehicle_info.vin else None
        
        if not search_vin:
            search_vin = f"TEMP-{uuid.uuid4().hex[:8].upper()}"
        
        vehicle = await Vehicle.find_one(Vehicle.vin == search_vin)
        
        if not vehicle:
            vehicle = Vehicle(
                customer_id=str(customer_id), # Ensure it's a string
                vin=search_vin,
                year=vehicle_info.year or 0,
                make=vehicle_info.make or "Unknown",
                model=vehicle_info.model or "Unknown",
                trim=vehicle_info.trim,
                engine=vehicle_info.engine,
                mileage=vehicle_info.mileage or 0
            )
            await vehicle.insert()
        else:
            # Update customer association (Crucial)
            vehicle.customer_id = str(customer_id)
            
            # Update details
            if vehicle_info.year: vehicle.year = vehicle_info.year
            if vehicle_info.make: vehicle.make = vehicle_info.make
            if vehicle_info.model: vehicle.model = vehicle_info.model
            if vehicle_info.trim: vehicle.trim = vehicle_info.trim
            if vehicle_info.engine: vehicle.engine = vehicle_info.engine
            if vehicle_info.mileage: vehicle.mileage = vehicle_info.mileage
            await vehicle.save()
        
        return vehicle
    
    def _create_estimate_items(
        self,
        labor_items: List[LaborItemSchema],
        parts_items: List[PartItemSchema]
    ) -> List[EstimateItem]:
        """Create estimate items list."""
        items = []
        
        for labor in labor_items:
            items.append(EstimateItem(
                item_type=ItemType.LABOR.value,
                description=labor.description or "Labor",
                quantity=1.0,
                unit_price=float(labor.rate or 0),
                labor_hours=float(labor.hours or 0),
                total=float(labor.total or 0)
            ))
        
        for part in parts_items:
            items.append(EstimateItem(
                item_type=ItemType.PART.value,
                description=part.description or "Part",
                quantity=float(part.quantity or 1),
                unit_price=float(part.cost or 0),
                markup_percentage=float(part.markup or 0),
                total=float(part.total or 0),
                vendor_name=part.vendor,
                part_number=part.partNumber
            ))
            
        return items