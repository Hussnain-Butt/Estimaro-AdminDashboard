"""
Auto-Generate Estimate Service

Orchestrates the entire estimate generation workflow automatically:
1. Decode VIN → Get vehicle info
2. Check NHTSA for recalls → Flag safety concerns
3. Check warranty status → Alert if under warranty
4. Service Request → Lookup labor times from ALLDATA
5. Labor items → Search for required parts from PartsLink24
6. Compare vendors (Worldpac/SSF) → Score and rank offers
7. Detect part conditions (NEW/REMAN) → CA BAR compliance
8. Calculate final estimate with cleaning kits

This is the "brain" that automates the entire estimation process.
"""
from typing import Dict, List, Optional
from decimal import Decimal


from app.services.vin_decoder_service import vin_decoder_service
from app.services.labor_service import labor_service
from app.services.parts_service import parts_service
from app.services.calculation_service import calculation_service
from app.services.recall_service import recall_service
from app.services.warranty_service import warranty_service
from app.services.vendor_service import vendor_service, VendorWeights
from app.services.part_condition_service import part_condition_service
from app.services.addon_service import addon_service
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
        customer_name: str = "",
        customer_phone: str = "",
        customer_email: str = "",
        odometer: int = 0,
        labor_rate: Decimal = Decimal("150"),
        parts_markup: Decimal = Decimal("30"),
        tax_rate: Decimal = Decimal("0.0925"),
        vendor_weights: Dict = None
    ) -> Dict:
        """
        Auto-generate complete estimate from VIN and service request.
        
        This is the main orchestration method that:
        1. Decodes VIN
        2. Checks for recalls
        3. Checks warranty status
        4. Looks up labor times
        5. Searches for parts
        6. Compares and scores vendors
        7. Detects part conditions
        8. Detects auto add-ons
        9. Calculates totals with cleaning kit
        
        Args:
            vin: Vehicle VIN
            service_request: Customer's service request description
            customer_name: Customer name
            customer_phone: Customer phone
            customer_email: Customer email
            odometer: Vehicle odometer reading (for warranty check)
            labor_rate: Shop labor rate (default $150/hr)
            parts_markup: Parts markup percentage (default 30%)
            tax_rate: Tax rate (default 9.25%)
            vendor_weights: Optional vendor scoring weights
            
        Returns:
            Complete estimate data with all steps populated
        """
        result = {
            "success": True,
            "steps": {},
            "flags": [],
            "errors": [],
            "customer": {
                "name": customer_name,
                "phone": customer_phone,
                "email": customer_email
            }
        }
        
        vehicle_info = None
        
        # =====================================================================
        # STEP 1: Decode VIN
        # =====================================================================
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
        
        # =====================================================================
        # STEP 2: NHTSA Recall Check
        # =====================================================================
        try:
            recall_result = await recall_service.check_recalls(vin, service_request)
            result["steps"]["recall_check"] = {
                "success": recall_result.get("success", True),
                "data": recall_result
            }
            
            # Add RED flag if matching recall found
            if recall_result.get("has_matching_recall"):
                result["flags"].append(recall_result["flag"])
        except Exception as e:
            result["steps"]["recall_check"] = {
                "success": False,
                "error": str(e)
            }
            # Non-critical - don't add to errors, just log
        
        # =====================================================================
        # STEP 3: Warranty Math Check
        # =====================================================================
        try:
            if vehicle_info and odometer > 0:
                warranty_result = warranty_service.check_warranty_status(
                    year=vehicle_info.year,
                    make=vehicle_info.make,
                    mileage=odometer,
                    service_request=service_request
                )
                result["steps"]["warranty_check"] = {
                    "success": warranty_result.get("success", True),
                    "data": warranty_result
                }
                
                # Add WARNING flag if likely under warranty
                if warranty_result.get("flag"):
                    result["flags"].append(warranty_result["flag"])
            else:
                result["steps"]["warranty_check"] = {
                    "success": True,
                    "data": {"skipped": True, "reason": "No odometer provided"}
                }
        except Exception as e:
            result["steps"]["warranty_check"] = {
                "success": False,
                "error": str(e)
            }
        
        # =====================================================================
        # STEP 4: Lookup Labor Times
        # =====================================================================
        labor_items = []
        job_type = "general"  # For cleaning kit selection
        try:
            labor_result = await labor_service.get_labor_time(vin, service_request)
            
            if labor_result:
                labor_items.append(LaborItemSchema(
                    description=labor_result.jobDescription,
                    hours=labor_result.laborHours,
                    rate=labor_rate,
                    total=labor_result.laborHours * labor_rate
                ))
                
                # Determine job type for cleaning kit
                job_type = self._detect_job_type(service_request)
                
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
                                "difficulty": labor_result.difficulty,
                                "job_type": job_type
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
        
        # =====================================================================
        # STEP 5: Search for Parts
        # =====================================================================
        parts_results = []
        parts_items = []
        try:
            parts_results = await parts_service.search_parts(vin, service_request)
            
            if parts_results:
                for part in parts_results:
                    parts_items.append(PartItemSchema(
                        description=part.description,
                        partNumber=part.partNumber or "",
                        quantity=Decimal("1"),
                        cost=part.price or Decimal("0"),
                        markup=parts_markup,
                        total=(part.price or Decimal("0")) * (Decimal("1") + parts_markup / Decimal("100")),
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
        
        # =====================================================================
        # STEP 6: Vendor Comparison & Scoring
        # =====================================================================
        try:
            if parts_results:
                # Set up vendor weights
                weights = VendorWeights()
                if vendor_weights:
                    weights = VendorWeights(
                        brand=vendor_weights.get("brand", 40),
                        price=vendor_weights.get("price", 35),
                        distance=vendor_weights.get("distance", 25)
                    )
                
                part_numbers = [p.partNumber for p in parts_results if p.partNumber]
                part_descriptions = [p.description for p in parts_results]
                
                vendor_result = await vendor_service.compare_vendors(
                    part_numbers=part_numbers,
                    part_descriptions=part_descriptions,
                    weights=weights
                )
                
                result["steps"]["vendor_compare"] = {
                    "success": vendor_result.get("success", True),
                    "data": vendor_result
                }
                
                # UPDATE parts_items with vendor prices
                # This ensures Parts tab shows actual prices, not $0.0
                vendor_parts = vendor_result.get("parts", [])
                for vendor_part in vendor_parts:
                    part_num = vendor_part.get("part_number", "")  # Correct field name
                    primary = vendor_part.get("primary", {})  # Primary vendor, not recommended
                    if primary:
                        vendor_price = Decimal(str(primary.get("price", "0") or "0"))
                        vendor_name = primary.get("vendor", "SSF")
                        
                        # Find and update matching part in parts_items
                        for item in parts_items:
                            if item.partNumber == part_num and item.cost == Decimal("0"):
                                item.cost = vendor_price
                                item.total = vendor_price * (Decimal("1") + item.markup / Decimal("100"))
                                item.vendor = vendor_name
            else:
                result["steps"]["vendor_compare"] = {
                    "success": True,
                    "data": {"skipped": True, "reason": "No parts to compare"}
                }
        except Exception as e:
            result["steps"]["vendor_compare"] = {
                "success": False,
                "error": str(e)
            }
        
        # =====================================================================
        # STEP 7: Part Condition Detection (CA BAR Compliance)
        # =====================================================================
        try:
            if parts_items: # Use parts_items which includes markup and quantity
                parts_for_condition = [
                    {
                        "description": p.description,
                        "manufacturer": p.vendor, # Use vendor as manufacturer for condition check
                        "partNumber": p.partNumber
                    }
                    for p in parts_items
                ]
                
                condition_result = part_condition_service.process_parts_list(parts_for_condition)
                
                result["steps"]["part_conditions"] = {
                    "success": condition_result.get("success", True),
                    "data": condition_result
                }
                
                # Add YELLOW flag if manual selection needed
                if condition_result.get("flag"):
                    result["flags"].append(condition_result["flag"])
            else:
                result["steps"]["part_conditions"] = {
                    "success": True,
                    "data": {"skipped": True, "reason": "No parts to check"}
                }
        except Exception as e:
            result["steps"]["part_conditions"] = {
                "success": False,
                "error": str(e)
            }
        
        # =====================================================================
        # STEP 8: Auto Add-On Detection
        # =====================================================================
        try:
            labor_procedures = [item.description for item in labor_items]
            addon_result = addon_service.detect_addons(service_request, labor_procedures)
            
            if addon_result.get("addons"):
                for addon in addon_result["addons"]:
                    # Add detected add-ons to parts list
                    parts_items.append(PartItemSchema(
                        description=addon["part_name"],
                        partNumber=addon.get("part_number", ""),
                        quantity=Decimal(str(addon["quantity"])),
                        cost=Decimal(str(addon["price"])),
                        markup=Decimal("0"), # No markup on auto-adds usually, or can make configurable
                        total=Decimal(str(addon["price"])) * Decimal(str(addon["quantity"])),
                        vendor="Auto-Add",
                        is_oem=False,
                        reason_badge=addon.get("reason_badge", "") # Add reason badge
                    ))
                    
                    # Add flag for user info
                    result["flags"].append({
                        "type": "INFO",
                        "severity": "low",
                        "message": f"Added {addon['part_name']}: {addon['reason']}"
                    })
            
            result["steps"]["addon_detection"] = {
                "success": True,
                "data": addon_result
            }
        except Exception as e:
            result["steps"]["addon_detection"] = {
                "success": False,
                "error": str(e)
            }
            # Non-critical - don't add to errors, just log
        
        # =====================================================================
        # STEP 9: Calculate Totals with Cleaning Kit
        # =====================================================================
        try:
            breakdown = calculation_service.calculate_estimate(
                labor_items=labor_items,
                parts_items=parts_items,
                job_type=job_type,
                tax_rate=tax_rate
            )
            
            result["steps"]["calculation"] = {
                "success": True,
                "data": {
                    "laborTotal": str(breakdown.laborTotal),
                    "partsTotal": str(breakdown.partsTotal),
                    "subtotal": str(breakdown.subtotal),
                    "taxAmount": str(breakdown.taxAmount),
                    "cleaningKit": breakdown.cleaningKit,
                    "total": str(breakdown.total)
                }
            }
        except Exception as e:
            result["steps"]["calculation"] = {
                "success": False,
                "error": str(e)
            }
            result["errors"].append(f"Calculation failed: {str(e)}")
        
        # =====================================================================
        # BUILD FINAL RESPONSE
        # =====================================================================
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
            "vendorComparison": result["steps"].get("vendor_compare", {}).get("data", {}),
            "partConditions": result["steps"].get("part_conditions", {}).get("data", {}),
            "breakdown": result["steps"].get("calculation", {}).get("data", {}),
            "recallCheck": result["steps"].get("recall_check", {}).get("data", {}),
            "warrantyCheck": result["steps"].get("warranty_check", {}).get("data", {})
        }
        
        # Calculate confidence score
        result["confidence_score"] = self._calculate_confidence_score(result)
        
        # Determine overall success
        critical_errors = [e for e in result["errors"] if "VIN" in e or "Labor" in e]
        result["success"] = len(critical_errors) == 0
        
        return result
    
    def _detect_job_type(self, service_request: str) -> str:
        """Detect job type for cleaning kit selection."""
        request_lower = service_request.lower()
        
        if any(kw in request_lower for kw in ['brake', 'pad', 'rotor', 'caliper']):
            return 'brake_service'
        elif any(kw in request_lower for kw in ['engine', 'motor', 'oil', 'gasket']):
            return 'engine_repair'
        elif any(kw in request_lower for kw in ['ac', 'air condition', 'a/c', 'compressor', 'freon']):
            return 'ac_service'
        else:
            return 'general'
    
    def _calculate_confidence_score(self, result: Dict) -> Dict:
        """Calculate confidence score based on step success and flags."""
        score = 100
        
        # Deduct for failed steps
        for step_name, step_data in result.get("steps", {}).items():
            if not step_data.get("success", True):
                if step_name in ["vehicle_decode", "labor_lookup"]:
                    score -= 30  # Critical steps
                else:
                    score -= 10  # Non-critical steps
        
        # Deduct for flags
        flags = result.get("flags", [])
        for flag in flags:
            flag_type = flag.get("type", "")
            if flag_type == "RED":
                score -= 20
            elif flag_type == "WARNING":
                score -= 10
            elif flag_type == "YELLOW":
                score -= 5
        
        score = max(0, score)
        
        # Determine threshold
        if score >= 90:
            threshold = "HIGH"
            action = "Auto-proceed"
        elif score >= 70:
            threshold = "MEDIUM"
            action = "Quick advisor review recommended"
        else:
            threshold = "LOW"
            action = "Human advisor required"
        
        return {
            "score": score,
            "percentage": f"{score}%",
            "threshold": threshold,
            "action": action
        }


# Singleton instance
auto_generate_service = AutoGenerateService()
