"""
Remote Scraper Adapters

These adapters call the Scraper Microservice running on the Windows RDP server
instead of doing local scraping. This enables the main backend to be deployed
anywhere while scraping is handled by the remote Windows server with Chrome.

IMPORTANT: These adapters raise exceptions on failure - NO FALLBACK DATA.
The frontend should display proper error messages to the user.
"""

import logging
from typing import Optional, List
from decimal import Decimal

from app.adapters.labor_adapter_interface import LaborAdapterInterface, LaborTimeResult
from app.adapters.parts_adapter_interface import PartsAdapterInterface, PartResult
from app.adapters.vendor_adapter_interface import VendorAdapterInterface, VendorPriceResult
from app.utils.scraper_client import scraper_client


logger = logging.getLogger(__name__)


class ScraperServiceError(Exception):
    """Exception raised when Scraper Service fails"""
    def __init__(self, service: str, error: str):
        self.service = service
        self.error = error
        super().__init__(f"{service} scraper failed: {error}")


class RemoteLaborAdapter(LaborAdapterInterface):
    """
    Labor adapter that calls the remote Scraper Service.
    Raises ScraperServiceError on failure - NO FALLBACK DATA.
    """
    
    async def get_labor_time(self, vin: str, job_description: str) -> Optional[LaborTimeResult]:
        logger.info(f"REMOTE LABOR: Requesting from Scraper Service for VIN={vin}")
        
        result = await scraper_client.get_labor_time(vin, job_description)
        
        if result.get("success"):
            return LaborTimeResult(
                jobDescription=job_description,
                laborHours=Decimal(str(result.get("labor_hours", 0))),
                source=result.get("source", "ALLDATA"),
                category="Remote Scraped",
                difficulty="Medium"
            )
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"REMOTE LABOR: Scraper failed - {error_msg}")
            raise ScraperServiceError("ALLDATA Labor", error_msg)


class RemotePartsAdapter(PartsAdapterInterface):
    """
    Parts adapter that calls the remote Scraper Service.
    Raises ScraperServiceError on failure - NO FALLBACK DATA.
    """
    
    async def search_parts(self, vin: str, job_description: str) -> List[PartResult]:
        logger.info(f"REMOTE PARTS: Requesting from Scraper Service for VIN={vin}")
        
        result = await scraper_client.get_parts(vin, job_description)
        
        if result.get("success"):
            parts = []
            for p in result.get("parts", []):
                # Skip placeholder parts
                part_num = p.get("part_number", "")
                if part_num and part_num != "MANUAL-LOOKUP":
                    parts.append(PartResult(
                        partNumber=part_num,
                        description=p.get("description", job_description),
                        manufacturer=p.get("manufacturer", "OEM"),
                        price=Decimal("0.00"),
                        isOEM=p.get("is_oem", True),
                        category="Remote Scraped"
                    ))
            
            if not parts:
                error_msg = f"No parts found for '{job_description}' on PartsLink24"
                logger.error(f"REMOTE PARTS: {error_msg}")
                raise ScraperServiceError("PartsLink24", error_msg)
            
            return parts
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"REMOTE PARTS: Scraper failed - {error_msg}")
            raise ScraperServiceError("PartsLink24 Parts", error_msg)


class RemoteVendorAdapter(VendorAdapterInterface):
    """
    Vendor pricing adapter that calls the remote Scraper Service.
    Raises ScraperServiceError on failure - NO FALLBACK DATA.
    """
    
    async def get_prices(self, part_numbers: List[str], vin: str = None, job_description: str = None) -> List[VendorPriceResult]:
        # Filter out placeholder part numbers
        valid_parts = [pn for pn in part_numbers if pn and pn != "MANUAL-LOOKUP"]
        
        if not valid_parts:
            logger.warning("REMOTE VENDOR: No valid part numbers to price")
            return []
        
        logger.info(f"REMOTE VENDOR: Requesting prices for {valid_parts}")
        if vin:
            logger.info(f"REMOTE VENDOR: Using VIN for Worldpac: {vin}")
        if job_description:
            logger.info(f"REMOTE VENDOR: Using Job for Worldpac: {job_description}")
        
        result = await scraper_client.get_pricing(valid_parts, vin=vin, job_description=job_description)
        
        if result.get("success"):
            prices = []
            for p in result.get("prices", []):
                prices.append(VendorPriceResult(
                    vendor_id=f"remote_{p.get('vendor', 'unknown')}",
                    vendor_name=p.get("vendor", "SSF"),
                    brand=p.get("brand", "Aftermarket"),
                    part_number=p.get("part_number", ""),
                    price=Decimal(str(p.get("price", 0))),
                    stock_status=p.get("stock_status", "In Stock"),
                    stock_quantity=1,
                    warehouse_location=p.get("warehouse", "Remote"),
                    warehouse_distance_miles=0,
                    delivery_option="Standard",
                    warranty="Manufacturer"
                ))
            return prices
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"REMOTE VENDOR: Scraper failed - {error_msg}")
            raise ScraperServiceError("SSF Pricing", error_msg)
