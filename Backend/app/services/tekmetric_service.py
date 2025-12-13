"""
Tekmetric Integration Service

This service handles integration with Tekmetric shop management system:
- Push estimates to Tekmetric
- Create repair orders (RO)
- Update RO status
- Link to customer records

Note: Requires Tekmetric API credentials configured in settings.
"""
from typing import Dict, Optional
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime
import httpx
import uuid

from app.core.config import settings


@dataclass
class TekmetricEstimate:
    """Data structure for Tekmetric estimate"""
    estimate_id: str
    ro_number: str
    customer_id: str
    vehicle_id: str
    status: str
    total_amount: Decimal
    created_at: datetime


class TekmetricService:
    """Service for Tekmetric API integration"""
    
    # Tekmetric API base URL (varies by shop)
    API_BASE = "https://api.tekmetric.com/v1"
    
    def __init__(self):
        self.api_key = getattr(settings, 'TEKMETRIC_API_KEY', None)
        self.shop_id = getattr(settings, 'TEKMETRIC_SHOP_ID', None)
        self.timeout = 30.0
    
    def _get_headers(self) -> Dict:
        """Get API headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def create_customer(
        self,
        name: str,
        phone: str,
        email: str = None
    ) -> Dict:
        """
        Create or find existing customer in Tekmetric.
        
        Args:
            name: Customer full name
            phone: Customer phone number
            email: Optional customer email
            
        Returns:
            Customer data with ID
        """
        if not self.api_key:
            # Mock response for development
            return {
                "success": True,
                "customer_id": f"CUST-{uuid.uuid4().hex[:8].upper()}",
                "name": name,
                "phone": phone,
                "email": email,
                "is_new": True,
                "mock": True
            }
        
        # Split name into first/last
        name_parts = name.strip().split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # First, try to find existing customer by phone
                search_response = await client.get(
                    f"{self.API_BASE}/customers",
                    headers=self._get_headers(),
                    params={"phone": phone, "shopId": self.shop_id}
                )
                
                if search_response.status_code == 200:
                    customers = search_response.json().get("data", [])
                    if customers:
                        return {
                            "success": True,
                            "customer_id": customers[0]["id"],
                            "name": name,
                            "is_new": False
                        }
                
                # Create new customer
                create_response = await client.post(
                    f"{self.API_BASE}/customers",
                    headers=self._get_headers(),
                    json={
                        "shopId": self.shop_id,
                        "firstName": first_name,
                        "lastName": last_name,
                        "phone": phone,
                        "email": email
                    }
                )
                
                if create_response.status_code in [200, 201]:
                    data = create_response.json()
                    return {
                        "success": True,
                        "customer_id": data.get("id"),
                        "name": name,
                        "is_new": True
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Failed to create customer: {create_response.text}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def create_vehicle(
        self,
        customer_id: str,
        vin: str,
        year: int,
        make: str,
        model: str,
        mileage: int = None
    ) -> Dict:
        """
        Create or find existing vehicle in Tekmetric.
        
        Args:
            customer_id: Tekmetric customer ID
            vin: Vehicle VIN
            year: Vehicle year
            make: Vehicle make
            model: Vehicle model
            mileage: Optional odometer reading
            
        Returns:
            Vehicle data with ID
        """
        if not self.api_key:
            # Mock response for development
            return {
                "success": True,
                "vehicle_id": f"VEH-{uuid.uuid4().hex[:8].upper()}",
                "vin": vin,
                "year": year,
                "make": make,
                "model": model,
                "mock": True
            }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # First, try to find existing vehicle by VIN
                search_response = await client.get(
                    f"{self.API_BASE}/vehicles",
                    headers=self._get_headers(),
                    params={"vin": vin, "shopId": self.shop_id}
                )
                
                if search_response.status_code == 200:
                    vehicles = search_response.json().get("data", [])
                    if vehicles:
                        return {
                            "success": True,
                            "vehicle_id": vehicles[0]["id"],
                            "vin": vin,
                            "is_new": False
                        }
                
                # Create new vehicle
                create_response = await client.post(
                    f"{self.API_BASE}/vehicles",
                    headers=self._get_headers(),
                    json={
                        "shopId": self.shop_id,
                        "customerId": customer_id,
                        "vin": vin,
                        "year": year,
                        "make": make,
                        "model": model,
                        "mileageIn": mileage
                    }
                )
                
                if create_response.status_code in [200, 201]:
                    data = create_response.json()
                    return {
                        "success": True,
                        "vehicle_id": data.get("id"),
                        "vin": vin,
                        "is_new": True
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Failed to create vehicle: {create_response.text}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def push_estimate(
        self,
        estimate_data: Dict
    ) -> Dict:
        """
        Push complete estimate to Tekmetric.
        
        This is the main method that:
        1. Creates/finds customer
        2. Creates/finds vehicle
        3. Creates repair order
        4. Adds line items (labor + parts)
        
        Args:
            estimate_data: Complete estimate data from auto_generate
            
        Returns:
            Tekmetric response with RO number and links
        """
        result = {
            "success": True,
            "steps": {}
        }
        
        # Extract data
        customer = estimate_data.get("customer", {})
        vehicle_info = estimate_data.get("vehicleInfo", {})
        labor_items = estimate_data.get("laborItems", [])
        parts_items = estimate_data.get("partsItems", [])
        breakdown = estimate_data.get("breakdown", {})
        
        # Step 1: Create/find customer
        customer_result = await self.create_customer(
            name=customer.get("name", ""),
            phone=customer.get("phone", ""),
            email=customer.get("email", "")
        )
        result["steps"]["customer"] = customer_result
        
        if not customer_result.get("success"):
            result["success"] = False
            result["error"] = "Failed to create customer"
            return result
        
        customer_id = customer_result.get("customer_id")
        
        # Step 2: Create/find vehicle
        vehicle_result = await self.create_vehicle(
            customer_id=customer_id,
            vin=vehicle_info.get("vin", ""),
            year=vehicle_info.get("year", 0),
            make=vehicle_info.get("make", ""),
            model=vehicle_info.get("model", ""),
            mileage=estimate_data.get("odometer")
        )
        result["steps"]["vehicle"] = vehicle_result
        
        if not vehicle_result.get("success"):
            result["success"] = False
            result["error"] = "Failed to create vehicle"
            return result
        
        vehicle_id = vehicle_result.get("vehicle_id")
        
        # Step 3: Create repair order with estimate
        ro_number = f"RO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        estimate_id = f"EST-{uuid.uuid4().hex[:8].upper()}"
        
        if not self.api_key:
            # Mock response for development
            result["steps"]["repair_order"] = {
                "success": True,
                "ro_number": ro_number,
                "estimate_id": estimate_id,
                "customer_id": customer_id,
                "vehicle_id": vehicle_id,
                "status": "estimate",
                "total": breakdown.get("total", "0.00"),
                "mock": True
            }
            result["tekmetric"] = {
                "ro_number": ro_number,
                "estimate_id": estimate_id,
                "status": "created",
                "view_url": f"https://app.tekmetric.com/ro/{ro_number}",
                "mock": True
            }
        else:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Create repair order
                    ro_response = await client.post(
                        f"{self.API_BASE}/repair-orders",
                        headers=self._get_headers(),
                        json={
                            "shopId": self.shop_id,
                            "customerId": customer_id,
                            "vehicleId": vehicle_id,
                            "status": "estimate"
                        }
                    )
                    
                    if ro_response.status_code in [200, 201]:
                        ro_data = ro_response.json()
                        ro_id = ro_data.get("id")
                        
                        # Add labor items
                        for labor in labor_items:
                            await client.post(
                                f"{self.API_BASE}/repair-orders/{ro_id}/labor",
                                headers=self._get_headers(),
                                json={
                                    "description": labor.get("description"),
                                    "hours": float(labor.get("hours", 0)),
                                    "rate": float(labor.get("rate", 0))
                                }
                            )
                        
                        # Add parts items
                        for part in parts_items:
                            await client.post(
                                f"{self.API_BASE}/repair-orders/{ro_id}/parts",
                                headers=self._get_headers(),
                                json={
                                    "description": part.get("description"),
                                    "partNumber": part.get("partNumber"),
                                    "quantity": float(part.get("quantity", 1)),
                                    "cost": float(part.get("cost", 0)),
                                    "price": float(part.get("total", 0))
                                }
                            )
                        
                        result["steps"]["repair_order"] = {
                            "success": True,
                            "ro_id": ro_id,
                            "ro_number": ro_data.get("roNumber", ro_number)
                        }
                        result["tekmetric"] = {
                            "ro_number": ro_data.get("roNumber", ro_number),
                            "estimate_id": ro_id,
                            "status": "created",
                            "view_url": f"https://app.tekmetric.com/ro/{ro_id}"
                        }
                    else:
                        result["success"] = False
                        result["error"] = f"Failed to create RO: {ro_response.text}"
                        
            except Exception as e:
                result["success"] = False
                result["error"] = str(e)
        
        return result
    
    async def update_ro_status(
        self,
        ro_id: str,
        status: str
    ) -> Dict:
        """
        Update repair order status.
        
        Args:
            ro_id: Tekmetric repair order ID
            status: New status (estimate, authorized, in_progress, complete, etc.)
            
        Returns:
            Update result
        """
        if not self.api_key:
            return {
                "success": True,
                "ro_id": ro_id,
                "status": status,
                "mock": True
            }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.patch(
                    f"{self.API_BASE}/repair-orders/{ro_id}",
                    headers=self._get_headers(),
                    json={"status": status}
                )
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "ro_id": ro_id,
                        "status": status
                    }
                else:
                    return {
                        "success": False,
                        "error": response.text
                    }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Singleton instance
tekmetric_service = TekmetricService()
