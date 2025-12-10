"""
Auto-Generate Estimate Service

Orchestrates the entire estimate generation workflow automatically:
1. Decode VIN → Get vehicle info
2. Service Request → Lookup labor times from ALLDATA
3. Labor items → Search for required parts from PartsLink24
4. Parts → Compare vendors (Worldpac/SSF) for best prices
5. Calculate final estimate with totals

This is the "brain" that automates the entire estimation process.
"""
from typing import Dict, List, Optional
from decimal import Decimal
from sqlalchemy.orm import Session

from app.services.vin_decoder_service import vin_decoder_service
from app.services.labor_service import labor_service
from app.services.parts_service import parts_service
from app.services.calculation_service import calculation_service
from app.schemas.estimate import (
    LaborItemSchema,
    PartItemSchema,
    CalculationBreakdownSchema
)


class AutoGenerateService:
    """Service for automatic estimate generation"""
    
    async def generate_estimate(
        self,
        vin: str,
        service_request: str,
        labor_rate: Decimal = Decimal("150")
    ) -> Dict:
        """
        Auto-generate complete estimate from VIN and service request.
        
        This is the main orchestration method that:
        1. Decodes VIN
        2. Looks up labor times
        3. Searches for parts
        4. Compares vendors (future)
        5. Calculates totals
        
        Args:
            vin: Vehicle VIN
            service_request: Customer's service request description
            labor_rate: Shop labor rate (default $150/hr)
            
        Returns:
            Complete estimate data with all steps populated
        """
        result = {
            "success": True,
            "steps": {},
            "errors": []
        }
        
        # Step 1: Decode VIN
        try:
            vehicle_info = await vin_decoder_service.decode_vin(vin)
            result["steps"]["vehicle_decode"] = {
                "success": True,
                "data": {
                    "vin": vehicle_info.vin,
                    "year": vehicle_info.year,
                    "make": vehicle_info.make,
                    "model": vehicle_info.model,
                    "trim": vehicle_info.trim,
                    "engine": vehicle_info.engine,
                }
            }
        except Exception as e:
            result["steps"]["vehicle_decode"] = {
                "success": False,
                "error": str(e)
            }
            result["errors"].append(f"VIN Decode failed: {str(e)}")
        
        # Step 2: Lookup Labor Times
        labor_items = []
        try:
            # Parse service request for multiple jobs
            # For now, treat entire service request as one job
            # Future: Parse multiple jobs from description
            labor_result = await labor_service.get_labor_time(vin, service_request)
            
            if labor_result:
                labor_items.append(LaborItemSchema(
                    description=labor_result.jobDescription,
                    hours=labor_result.laborHours,
                    rate=labor_rate,
                    total=labor_result.laborHours * labor_rate
                ))
                
                result["steps"]["labor_lookup"] = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "description": labor_result.jobDescription,
                                "hours": str(labor_result.laborHours),
                                "rate": str(labor_rate),
                                "source": labor_result.source,
                                "category": labor_result.category,
                                "difficulty": labor_result.difficulty
                            }
                        ]
                    }
                }
            else:
                result["steps"]["labor_lookup"] = {
                    "success": False,
                    "error": "No labor time found"
                }
                result["errors"].append("Labor lookup returned no results")
        except Exception as e:
            result["steps"]["labor_lookup"] = {
                "success": False,
                "error": str(e)
            }
            result["errors"].append(f"Labor lookup failed: {str(e)}")
        
        # Step 3: Search for Parts
        parts_items = []
        try:
            # Search parts based on service request
            parts_results = await parts_service.search_parts(vin, service_request)
            
            if parts_results:
                for part in parts_results:
                    parts_items.append(PartItemSchema(
                        description=part.description,
                        partNumber=part.partNumber or "",
                        quantity=Decimal("1"),
                        cost=part.price or Decimal("0"),
                        markup=Decimal("30"),  # Default 30% markup
                        total=(part.price or Decimal("0")) * Decimal("1.30"),
                        vendor=part.manufacturer or "Unknown"
                    ))
                
                result["steps"]["parts_search"] = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "description": part.description,
                                "partNumber": part.partNumber,
                                "manufacturer": part.manufacturer,
                                "price": str(part.price),
                                "isOEM": part.isOEM,
                                "category": part.category
                            }
                            for part in parts_results
                        ]
                    }
                }
            else:
                result["steps"]["parts_search"] = {
                    "success": True,
                    "data": {"items": []},
                    "warning": "No parts found"
                }
        except Exception as e:
            result["steps"]["parts_search"] = {
                "success": False,
                "error": str(e)
            }
            result["errors"].append(f"Parts search failed: {str(e)}")
        
        # Step 4: Vendor Compare (Future Implementation)
        # For now, we'll use the parts from PartsLink24 as-is
        # Future: Compare prices from Worldpac and SSF
        result["steps"]["vendor_compare"] = {
            "success": True,
            "data": {
                "primary_vendor": "PartsLink24",
                "note": "Vendor comparison coming soon"
            }
        }
        
        # Step 5: Calculate Totals
        try:
            breakdown = calculation_service.calculate_estimate(
                labor_items=labor_items,
                parts_items=parts_items
            )
            
            result["steps"]["calculation"] = {
                "success": True,
                "data": {
                    "laborTotal": str(breakdown.laborTotal),
                    "partsTotal": str(breakdown.partsTotal),
                    "subtotal": str(breakdown.subtotal),
                    "taxAmount": str(breakdown.taxAmount),
                    "total": str(breakdown.total)
                }
            }
        except Exception as e:
            result["steps"]["calculation"] = {
                "success": False,
                "error": str(e)
            }
            result["errors"].append(f"Calculation failed: {str(e)}")
        
        # Build final response
        result["estimate_data"] = {
            "vehicleInfo": result["steps"].get("vehicle_decode", {}).get("data", {}),
            "laborItems": [
                {
                    "description": item.description,
                    "hours": str(item.hours),
                    "rate": str(item.rate),
                    "total": str(item.total)
                }
                for item in labor_items
            ],
            "partsItems": [
                {
                    "description": item.description,
                    "partNumber": item.partNumber,
                    "quantity": str(item.quantity),
                    "cost": str(item.cost),
                    "markup": str(item.markup),
                    "total": str(item.total),
                    "vendor": item.vendor
                }
                for item in parts_items
            ],
            "breakdown": result["steps"].get("calculation", {}).get("data", {})
        }
        
        # Determine overall success
        result["success"] = len(result["errors"]) == 0
        
        return result


# Singleton instance
auto_generate_service = AutoGenerateService()
