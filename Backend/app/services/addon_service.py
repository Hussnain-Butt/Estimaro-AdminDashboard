"""
Auto Add-On Detection Service

This service automatically detects required add-on items based on:
- Labor procedure steps
- Job type keywords
- Disassembly requirements

Add-ons include gaskets, sealers, fluids, and consumables that are
commonly required but often forgotten.
"""
from typing import Dict, List, Optional
from decimal import Decimal
from dataclasses import dataclass


@dataclass
class AddOnItem:
    """Auto-detected add-on item"""
    part_name: str
    part_number: str
    category: str
    price: Decimal
    quantity: int
    reason: str
    reason_badge: str


# Add-on detection rules
ADD_ON_RULES = {
    "plenum_removal": {
        "keywords": ["plenum removal", "intake manifold removal", "remove plenum", "remove intake manifold"],
        "add_items": [
            {
                "part_name": "Intake Plenum Gasket",
                "part_number": "PLN-GSK-001",
                "category": "gaskets",
                "price": Decimal("24.99"),
                "reason": "Plenum must be resealed after removal"
            },
            {
                "part_name": "Intake Manifold Gasket Set",
                "part_number": "INT-GSK-SET",
                "category": "gaskets",
                "price": Decimal("34.99"),
                "reason": "Required for manifold reassembly"
            }
        ]
    },
    "valve_cover": {
        "keywords": ["valve cover", "remove valve cover", "valve cover gasket"],
        "add_items": [
            {
                "part_name": "Valve Cover Gasket",
                "part_number": "VC-GSK-001",
                "category": "gaskets",
                "price": Decimal("28.99"),
                "reason": "Always replace when removing valve cover"
            },
            {
                "part_name": "Spark Plug Tube Seals",
                "part_number": "SP-SEAL-SET",
                "category": "seals",
                "price": Decimal("18.99"),
                "reason": "Prevents oil leaks into spark plug wells"
            }
        ]
    },
    "brake_service": {
        "keywords": ["brake pad", "brake service", "brake rotor", "brake caliper", "replace pads"],
        "add_items": [
            {
                "part_name": "Brake Cleaner",
                "part_number": "BC-CLN-001",
                "category": "consumables",
                "price": Decimal("8.99"),
                "reason": "Required for proper brake pad installation"
            },
            {
                "part_name": "Anti-Seize Compound",
                "part_number": "AS-CMP-001",
                "category": "consumables",
                "price": Decimal("12.99"),
                "reason": "Prevents caliper slide pin seizure"
            },
            {
                "part_name": "Brake Hardware Kit",
                "part_number": "BRK-HW-KIT",
                "category": "hardware",
                "price": Decimal("15.99"),
                "reason": "Includes clips and springs for proper operation"
            }
        ]
    },
    "coolant_system": {
        "keywords": ["coolant flush", "radiator flush", "thermostat", "water pump", "coolant leak"],
        "add_items": [
            {
                "part_name": "Coolant/Antifreeze (1 gal)",
                "part_number": "CLT-AF-001",
                "category": "fluids",
                "price": Decimal("24.99"),
                "reason": "System refill after service"
            },
            {
                "part_name": "Radiator Cap",
                "part_number": "RAD-CAP-001",
                "category": "parts",
                "price": Decimal("12.99"),
                "reason": "Inspect/replace when servicing cooling system"
            },
            {
                "part_name": "Thermostat Gasket",
                "part_number": "THM-GSK-001",
                "category": "gaskets",
                "price": Decimal("8.99"),
                "reason": "Required when replacing thermostat"
            }
        ]
    },
    "oil_change": {
        "keywords": ["oil change", "engine oil", "oil filter"],
        "add_items": [
            {
                "part_name": "Drain Plug Gasket",
                "part_number": "DRN-GSK-001",
                "category": "gaskets",
                "price": Decimal("2.99"),
                "reason": "Replace every oil change to prevent leaks"
            }
        ]
    },
    "timing_belt": {
        "keywords": ["timing belt", "timing chain", "timing tensioner"],
        "add_items": [
            {
                "part_name": "Timing Belt Tensioner",
                "part_number": "TM-TNS-001",
                "category": "parts",
                "price": Decimal("89.99"),
                "reason": "Always replace with timing belt"
            },
            {
                "part_name": "Timing Belt Idler Pulley",
                "part_number": "TM-IDL-001",
                "category": "parts",
                "price": Decimal("34.99"),
                "reason": "Wear item - replace with belt"
            },
            {
                "part_name": "Water Pump",
                "part_number": "WP-001",
                "category": "parts",
                "price": Decimal("79.99"),
                "reason": "Recommended replacement - already accessible"
            }
        ]
    },
    "transmission_service": {
        "keywords": ["transmission fluid", "trans flush", "transmission service", "atf"],
        "add_items": [
            {
                "part_name": "Transmission Filter Kit",
                "part_number": "TRS-FLT-KIT",
                "category": "filters",
                "price": Decimal("45.99"),
                "reason": "Replace filter when servicing transmission"
            },
            {
                "part_name": "Transmission Pan Gasket",
                "part_number": "TRS-PAN-GSK",
                "category": "gaskets",
                "price": Decimal("18.99"),
                "reason": "Replace when removing pan"
            }
        ]
    },
    "exhaust_work": {
        "keywords": ["exhaust", "catalytic converter", "muffler", "exhaust manifold"],
        "add_items": [
            {
                "part_name": "Exhaust Gasket",
                "part_number": "EXH-GSK-001",
                "category": "gaskets",
                "price": Decimal("14.99"),
                "reason": "Required for exhaust connections"
            },
            {
                "part_name": "Exhaust Bolts/Studs Kit",
                "part_number": "EXH-HW-KIT",
                "category": "hardware",
                "price": Decimal("22.99"),
                "reason": "Often corroded and break during removal"
            }
        ]
    },
    "suspension": {
        "keywords": ["strut", "shock", "control arm", "ball joint", "tie rod"],
        "add_items": [
            {
                "part_name": "Alignment Service",
                "part_number": "SVC-ALIGN",
                "category": "labor",
                "price": Decimal("89.99"),
                "reason": "Required after suspension work"
            }
        ]
    },
    "ac_service": {
        "keywords": ["ac", "a/c", "air conditioning", "compressor", "condenser", "evaporator"],
        "add_items": [
            {
                "part_name": "R-134a Refrigerant",
                "part_number": "AC-R134A",
                "category": "fluids",
                "price": Decimal("45.99"),
                "reason": "System recharge after repair"
            },
            {
                "part_name": "AC O-Ring Kit",
                "part_number": "AC-ORING-KIT",
                "category": "seals",
                "price": Decimal("18.99"),
                "reason": "Replace seals to prevent leaks"
            },
            {
                "part_name": "PAG Oil",
                "part_number": "AC-PAG-OIL",
                "category": "fluids",
                "price": Decimal("22.99"),
                "reason": "Required for compressor lubrication"
            }
        ]
    }
}


class AddOnService:
    """Service for automatic add-on detection"""
    
    def detect_addons(
        self,
        service_request: str,
        labor_procedures: List[str] = None
    ) -> Dict:
        """
        Detect required add-on items based on service request and procedures.
        
        Args:
            service_request: Customer's service description
            labor_procedures: Optional list of procedure steps from labor lookup
            
        Returns:
            Dict with detected add-ons
        """
        detected_addons = []
        matched_rules = []
        
        # Combine search text
        search_text = service_request.lower()
        if labor_procedures:
            search_text += " " + " ".join(labor_procedures).lower()
        
        # Check each rule
        for rule_name, rule_data in ADD_ON_RULES.items():
            # Check if any keywords match
            for keyword in rule_data["keywords"]:
                if keyword.lower() in search_text:
                    matched_rules.append(rule_name)
                    
                    # Add the items from this rule
                    for item in rule_data["add_items"]:
                        addon = AddOnItem(
                            part_name=item["part_name"],
                            part_number=item["part_number"],
                            category=item["category"],
                            price=item["price"],
                            quantity=1,
                            reason=item["reason"],
                            reason_badge=f"{rule_name.replace('_', ' ').title()} → {item['part_name']}"
                        )
                        
                        # Avoid duplicates
                        if not any(a.part_number == addon.part_number for a in detected_addons):
                            detected_addons.append(addon)
                    
                    break  # Only match each rule once
        
        # Calculate totals
        total_price = sum(item.price * item.quantity for item in detected_addons)
        
        return {
            "success": True,
            "matched_rules": list(set(matched_rules)),
            "addon_count": len(detected_addons),
            "addons": [
                {
                    "part_name": item.part_name,
                    "part_number": item.part_number,
                    "category": item.category,
                    "price": str(item.price),
                    "quantity": item.quantity,
                    "reason": item.reason,
                    "reason_badge": item.reason_badge
                }
                for item in detected_addons
            ],
            "total_price": str(total_price),
            "note": "Recommended items based on job type - can be removed by advisor"
        }
    
    def get_available_rules(self) -> List[str]:
        """Get list of all available add-on rule names."""
        return list(ADD_ON_RULES.keys())
    
    def get_rule_details(self, rule_name: str) -> Optional[Dict]:
        """Get details for a specific add-on rule."""
        return ADD_ON_RULES.get(rule_name)


# Singleton instance
addon_service = AddOnService()
