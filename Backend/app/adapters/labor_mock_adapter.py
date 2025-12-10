"""
Mock Labor Adapter

Mock implementation of labor time lookup.
Returns hardcoded labor times for common jobs.

This will be replaced with ALLDATA adapter when API keys are available.
"""
from typing import Optional, Dict
from decimal import Decimal
from app.adapters.labor_adapter_interface import LaborAdapterInterface, LaborTimeResult


class LaborMockAdapter(LaborAdapterInterface):
    """Mock adapter for labor time lookup"""
    
    # Hardcoded labor times for common jobs (in hours)
    LABOR_DATABASE: Dict[str, Dict] = {
        # Brake Jobs
        "brake pad": {
            "hours": Decimal("1.5"),
            "category": "Brakes",
            "difficulty": "Medium",
            "description": "Brake Pad Replacement"
        },
        "brake rotor": {
            "hours": Decimal("2.0"),
            "category": "Brakes",
            "difficulty": "Medium",
            "description": "Brake Rotor Replacement"
        },
        "brake caliper": {
            "hours": Decimal("1.8"),
            "category": "Brakes",
            "difficulty": "Medium",
            "description": "Brake Caliper Replacement"
        },
        
        # Oil & Fluids
        "oil change": {
            "hours": Decimal("0.5"),
            "category": "Maintenance",
            "difficulty": "Easy",
            "description": "Oil Change"
        },
        "transmission fluid": {
            "hours": Decimal("1.0"),
            "category": "Maintenance",
            "difficulty": "Medium",
            "description": "Transmission Fluid Change"
        },
        "coolant flush": {
            "hours": Decimal("1.2"),
            "category": "Cooling System",
            "difficulty": "Medium",
            "description": "Coolant Flush"
        },
        
        # Timing Belt
        "timing belt": {
            "hours": Decimal("4.5"),
            "category": "Engine",
            "difficulty": "Hard",
            "description": "Timing Belt Replacement"
        },
        
        # Suspension
        "shock absorber": {
            "hours": Decimal("2.5"),
            "category": "Suspension",
            "difficulty": "Medium",
            "description": "Shock Absorber Replacement"
        },
        "strut": {
            "hours": Decimal("3.0"),
            "category": "Suspension",
            "difficulty": "Hard",
            "description": "Strut Replacement"
        },
        
        # Battery & Electrical
        "battery": {
            "hours": Decimal("0.3"),
            "category": "Electrical",
            "difficulty": "Easy",
            "description": "Battery Replacement"
        },
        "alternator": {
            "hours": Decimal("2.0"),
            "category": "Electrical",
            "difficulty": "Medium",
            "description": "Alternator Replacement"
        },
        "starter": {
            "hours": Decimal("1.5"),
            "category": "Electrical",
            "difficulty": "Medium",
            "description": "Starter Replacement"
        },
        
        # Tires
        "tire rotation": {
            "hours": Decimal("0.5"),
            "category": "Tires",
            "difficulty": "Easy",
            "description": "Tire Rotation"
        },
        "tire replacement": {
            "hours": Decimal("1.0"),
            "category": "Tires",
            "difficulty": "Easy",
            "description": "Tire Replacement (Set of 4)"
        },
        
        # Air Filters
        "air filter": {
            "hours": Decimal("0.3"),
            "category": "Maintenance",
            "difficulty": "Easy",
            "description": "Engine Air Filter Replacement"
        },
        "cabin filter": {
            "hours": Decimal("0.3"),
            "category": "Maintenance",
            "difficulty": "Easy",
            "description": "Cabin Air Filter Replacement"
        },
    }
    
    async def get_labor_time(
        self,
        vin: str,
        job_description: str
    ) -> Optional[LaborTimeResult]:
        """
        Get labor time from mock database using keyword matching.
        
        Args:
            vin: Vehicle VIN (not used in mock, but required by interface)
            job_description: Job description to search for
            
        Returns:
            Labor time result or None if not found
        """
        # Convert to lowercase for case-insensitive matching
        search_term = job_description.lower()
        
        # Try to find matching job by keyword
        for keyword, job_data in self.LABOR_DATABASE.items():
            if keyword in search_term:
                return LaborTimeResult(
                    jobDescription=job_data["description"],
                    laborHours=job_data["hours"],
                    source="mock",
                    category=job_data["category"],
                    difficulty=job_data["difficulty"]
                )
        
        # If no match found, return a default estimate
        return LaborTimeResult(
            jobDescription=job_description,
            laborHours=Decimal("1.0"),  # Default 1 hour
            source="mock",
            category="General",
            difficulty="Unknown"
        )
