"""
Warranty Service - Warranty Math Check

This service calculates warranty status using the "Math Method":
- < 3 years + < 36k miles → Bumper-to-Bumper
- < 5 years + < 60k miles → Powertrain
- Hyundai/Kia: 10 years / 100k miles special rule

Alerts advisors when vehicle may be under factory warranty.
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class WarrantyType(Enum):
    """Types of factory warranties"""
    BUMPER_TO_BUMPER = "Bumper-to-Bumper"
    POWERTRAIN = "Powertrain"
    EXTENDED_POWERTRAIN = "Extended Powertrain"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    CAUTION = "CAUTION"


@dataclass
class WarrantyAlert:
    """Warranty alert information"""
    alert_level: AlertLevel
    warranty_type: WarrantyType
    message: str
    action: str
    coverage_details: str


class WarrantyService:
    """Service for warranty status checks"""
    
    # Standard warranty terms (years, miles)
    STANDARD_WARRANTIES = {
        "bumper_to_bumper": {"years": 3, "miles": 36000},
        "powertrain": {"years": 5, "miles": 60000}
    }
    
    # Manufacturer-specific warranty terms
    MANUFACTURER_WARRANTIES = {
        "HYUNDAI": {
            "bumper_to_bumper": {"years": 5, "miles": 60000},
            "powertrain": {"years": 10, "miles": 100000}
        },
        "KIA": {
            "bumper_to_bumper": {"years": 5, "miles": 60000},
            "powertrain": {"years": 10, "miles": 100000}
        },
        "GENESIS": {
            "bumper_to_bumper": {"years": 5, "miles": 60000},
            "powertrain": {"years": 10, "miles": 100000}
        },
        "MITSUBISHI": {
            "bumper_to_bumper": {"years": 5, "miles": 60000},
            "powertrain": {"years": 10, "miles": 100000}
        },
        # BMW and Mercedes have 4-year warranties
        "BMW": {
            "bumper_to_bumper": {"years": 4, "miles": 50000},
            "powertrain": {"years": 4, "miles": 50000}
        },
        "MERCEDES-BENZ": {
            "bumper_to_bumper": {"years": 4, "miles": 50000},
            "powertrain": {"years": 4, "miles": 50000}
        },
        "MERCEDES": {
            "bumper_to_bumper": {"years": 4, "miles": 50000},
            "powertrain": {"years": 4, "miles": 50000}
        }
    }
    
    # Components covered by powertrain warranty
    POWERTRAIN_COMPONENTS = [
        'engine', 'motor', 'transmission', 'transaxle', 'transfer case',
        'drive shaft', 'differential', 'axle', 'turbo', 'supercharger'
    ]
    
    def get_warranty_terms(self, make: str) -> Dict:
        """
        Get warranty terms for a specific manufacturer.
        
        Args:
            make: Vehicle manufacturer name
            
        Returns:
            Dict with warranty terms
        """
        make_upper = make.upper().strip()
        
        if make_upper in self.MANUFACTURER_WARRANTIES:
            return self.MANUFACTURER_WARRANTIES[make_upper]
        
        return self.STANDARD_WARRANTIES
    
    def calculate_vehicle_age(self, model_year: int) -> int:
        """
        Calculate vehicle age in years.
        
        Args:
            model_year: Vehicle model year
            
        Returns:
            Age in years
        """
        current_year = datetime.now().year
        return current_year - model_year
    
    def is_powertrain_related(self, service_request: str) -> bool:
        """
        Check if service request involves powertrain components.
        
        Args:
            service_request: Customer's service request description
            
        Returns:
            True if powertrain-related
        """
        if not service_request:
            return False
        
        request_lower = service_request.lower()
        return any(comp in request_lower for comp in self.POWERTRAIN_COMPONENTS)
    
    def check_warranty_status(
        self,
        year: int,
        make: str,
        mileage: int,
        service_request: str = ""
    ) -> Dict:
        """
        Check warranty status using the "Math Method".
        
        Args:
            year: Vehicle model year
            make: Vehicle manufacturer
            mileage: Current odometer reading
            service_request: Optional service request for powertrain check
            
        Returns:
            Dict with warranty check results
        """
        result = {
            "success": True,
            "vehicle_age_years": 0,
            "mileage": mileage,
            "make": make,
            "warranty_terms": {},
            "alerts": [],
            "likely_under_warranty": False,
            "flag": None
        }
        
        # Calculate vehicle age
        vehicle_age = self.calculate_vehicle_age(year)
        result["vehicle_age_years"] = vehicle_age
        
        # Get warranty terms for this manufacturer
        warranty_terms = self.get_warranty_terms(make)
        result["warranty_terms"] = {
            "bumper_to_bumper": f"{warranty_terms['bumper_to_bumper']['years']} years / {warranty_terms['bumper_to_bumper']['miles']:,} miles",
            "powertrain": f"{warranty_terms['powertrain']['years']} years / {warranty_terms['powertrain']['miles']:,} miles"
        }
        
        alerts = []
        
        # Check Bumper-to-Bumper warranty
        btb = warranty_terms["bumper_to_bumper"]
        if vehicle_age < btb["years"] and mileage < btb["miles"]:
            alerts.append(WarrantyAlert(
                alert_level=AlertLevel.WARNING,
                warranty_type=WarrantyType.BUMPER_TO_BUMPER,
                message=f"Vehicle likely under BUMPER-TO-BUMPER warranty",
                action="Verify with customer before proceeding",
                coverage_details=f"{btb['years']} years / {btb['miles']:,} miles"
            ))
            result["likely_under_warranty"] = True
        
        # Check Powertrain warranty
        pwr = warranty_terms["powertrain"]
        is_powertrain = self.is_powertrain_related(service_request)
        
        if vehicle_age < pwr["years"] and mileage < pwr["miles"]:
            alert_level = AlertLevel.WARNING if is_powertrain else AlertLevel.INFO
            
            alerts.append(WarrantyAlert(
                alert_level=alert_level,
                warranty_type=WarrantyType.POWERTRAIN,
                message=f"Vehicle may have POWERTRAIN warranty coverage",
                action="Check if repair is powertrain-related" if not is_powertrain else "Powertrain repair - likely covered!",
                coverage_details=f"{pwr['years']} years / {pwr['miles']:,} miles"
            ))
            
            if is_powertrain:
                result["likely_under_warranty"] = True
        
        # Check for extended warranties (Hyundai/Kia/Genesis)
        make_upper = make.upper()
        if make_upper in ["HYUNDAI", "KIA", "GENESIS"]:
            if vehicle_age < 10 and mileage < 100000:
                alerts.append(WarrantyAlert(
                    alert_level=AlertLevel.WARNING,
                    warranty_type=WarrantyType.EXTENDED_POWERTRAIN,
                    message=f"{make} 10-year/100k powertrain warranty may apply",
                    action="Verify coverage before proceeding",
                    coverage_details="10 years / 100,000 miles"
                ))
        
        # Convert alerts to serializable format
        result["alerts"] = [
            {
                "level": a.alert_level.value,
                "type": a.warranty_type.value,
                "message": a.message,
                "action": a.action,
                "coverage": a.coverage_details
            }
            for a in alerts
        ]
        
        # Create summary flag if under warranty
        if result["likely_under_warranty"]:
            primary_alert = alerts[0] if alerts else None
            result["flag"] = {
                "type": "WARNING",
                "title": "⚠️ WARRANTY ALERT",
                "message": f"This {year} {make} with {mileage:,} miles is likely still under factory warranty",
                "action": "Consider referring customer to dealer for warranty repair",
                "options": ["Proceed Anyway", "Refer to Dealer"]
            }
        
        return result


# Singleton instance
warranty_service = WarrantyService()
