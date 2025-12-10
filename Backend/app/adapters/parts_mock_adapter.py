"""
Mock Parts Adapter

Mock implementation of parts lookup.
Returns hardcoded parts for common jobs.

This will be replaced with PartsLink24 adapter when API keys are available.
"""
from typing import List, Dict
from decimal import Decimal
from app.adapters.parts_adapter_interface import PartsAdapterInterface, PartResult


class PartsMockAdapter(PartsAdapterInterface):
    """Mock adapter for parts lookup"""
    
    # Hardcoded parts database
    PARTS_DATABASE: Dict[str, List[Dict]] = {
        # Brake Parts
        "brake pad": [
            {
                "partNumber": "BRK-PAD-001",
                "description": "Brake Pad Set - Front (OEM)",
                "manufacturer": "OEM",
                "price": Decimal("85.00"),
                "isOEM": True,
                "category": "Brakes"
            },
            {
                "partNumber": "BRK-PAD-002",
                "description": "Brake Pad Set - Front (Aftermarket)",
                "manufacturer": "Wagner",
                "price": Decimal("45.00"),
                "isOEM": False,
                "category": "Brakes"
            }
        ],
        "brake rotor": [
            {
                "partNumber": "BRK-ROT-001",
                "description": "Brake Rotor - Front (Pair)",
                "manufacturer": "OEM",
                "price": Decimal("120.00"),
                "isOEM": True,
                "category": "Brakes"
            }
        ],
        "brake caliper": [
            {
                "partNumber": "BRK-CAL-001",
                "description": "Brake Caliper - Front Left",
                "manufacturer": "OEM",
                "price": Decimal("150.00"),
                "isOEM": True,
                "category": "Brakes"
            }
        ],
        
        # Oil & Filters
        "oil": [
            {
                "partNumber": "OIL-001",
                "description": "Engine Oil 5W-30 (5 Quarts)",
                "manufacturer": "Mobil 1",
                "price": Decimal("28.00"),
                "isOEM": False,
                "category": "Fluids"
            }
        ],
        "oil filter": [
            {
                "partNumber": "OIL-FLT-001",
                "description": "Oil Filter",
                "manufacturer": "OEM",
                "price": Decimal("8.00"),
                "isOEM": True,
                "category": "Filters"
            }
        ],
        "air filter": [
            {
                "partNumber": "AIR-FLT-001",
                "description": "Engine Air Filter",
                "manufacturer": "OEM",
                "price": Decimal("18.00"),
                "isOEM": True,
                "category": "Filters"
            }
        ],
        "cabin filter": [
            {
                "partNumber": "CAB-FLT-001",
                "description": "Cabin Air Filter",
                "manufacturer": "OEM",
                "price": Decimal("15.00"),
                "isOEM": True,
                "category": "Filters"
            }
        ],
        
        # Timing Belt
        "timing belt": [
            {
                "partNumber": "TIM-BLT-001",
                "description": "Timing Belt Kit (Belt + Tensioner)",
                "manufacturer": "OEM",
                "price": Decimal("180.00"),
                "isOEM": True,
                "category": "Engine"
            }
        ],
        
        # Suspension
        "shock": [
            {
                "partNumber": "SUS-SHK-001",
                "description": "Shock Absorber - Front (Each)",
                "manufacturer": "Monroe",
                "price": Decimal("75.00"),
                "isOEM": False,
                "category": "Suspension"
            }
        ],
        "strut": [
            {
                "partNumber": "SUS-STR-001",
                "description": "Strut Assembly - Front (Each)",
                "manufacturer": "OEM",
                "price": Decimal("220.00"),
                "isOEM": True,
                "category": "Suspension"
            }
        ],
        
        # Battery & Electrical
        "battery": [
            {
                "partNumber": "BAT-001",
                "description": "Battery - Group 24F",
                "manufacturer": "Interstate",
                "price": Decimal("120.00"),
                "isOEM": False,
                "category": "Electrical"
            }
        ],
        "alternator": [
            {
                "partNumber": "ALT-001",
                "description": "Alternator - Remanufactured",
                "manufacturer": "OEM",
                "price": Decimal("280.00"),
                "isOEM": True,
                "category": "Electrical"
            }
        ],
        "starter": [
            {
                "partNumber": "STR-001",
                "description": "Starter Motor - Remanufactured",
                "manufacturer": "OEM",
                "price": Decimal("180.00"),
                "isOEM": True,
                "category": "Electrical"
            }
        ],
        
        # Coolant
        "coolant": [
            {
                "partNumber": "CLT-001",
                "description": "Engine Coolant (1 Gallon)",
                "manufacturer": "OEM",
                "price": Decimal("22.00"),
                "isOEM": True,
                "category": "Fluids"
            }
        ],
    }
    
    async def search_parts(
        self,
        vin: str,
        job_description: str
    ) -> List[PartResult]:
        """
        Search for parts from mock database using keyword matching.
        
        Args:
            vin: Vehicle VIN (not used in mock, but required by interface)
            job_description: Job description to search for
            
        Returns:
            List of matching parts
        """
        # Convert to lowercase for case-insensitive matching
        search_term = job_description.lower()
        
        results = []
        
        # Try to find matching parts by keyword
        for keyword, parts_list in self.PARTS_DATABASE.items():
            if keyword in search_term:
                for part_data in parts_list:
                    results.append(PartResult(**part_data))
        
        # If no match found, return a generic part
        if not results:
            results.append(PartResult(
                partNumber="GEN-001",
                description=f"Generic Part for: {job_description}",
                manufacturer="Generic",
                price=Decimal("50.00"),
                isOEM=False,
                category="General"
            ))
        
        return results
