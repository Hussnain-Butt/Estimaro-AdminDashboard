from abc import ABC, abstractmethod
from typing import List, Optional
from decimal import Decimal
from dataclasses import dataclass
# We can import VendorOffer from vendor_service, but circular imports might be tricky.
# Better to define the result DTO here or share it. 
# For simplicity, I'll redefine a simple DTO or try to import if possible.
# Actually, VendorOffer is in services/vendor_service.py. Ideally it should be in schemas or models.
# I will create a standalone DTO here to avoid circular dependency with service.

@dataclass
class VendorPriceResult:
    vendor_id: str
    vendor_name: str
    brand: str
    part_number: str
    price: Decimal
    stock_status: str
    stock_quantity: int
    warehouse_location: str
    warehouse_distance_miles: float
    delivery_option: str
    warranty: str

class VendorAdapterInterface(ABC):
    """Abstract interface for Vendor Pricing Scrapers (Worldpac, SSF, etc.)"""

    @abstractmethod
    async def get_prices(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        """
        Scrape pricing for valid OEM part numbers.
        """
        pass
