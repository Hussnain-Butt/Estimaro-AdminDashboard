"""
Remote Scraper Adapters

These adapters call the Scraper Microservice running on the Windows RDP server
instead of doing local scraping. This enables the main backend to be deployed
anywhere while scraping is handled by the remote Windows server with Chrome.

Usage:
  Set LABOR_ADAPTER_TYPE=remote in .env to use RemoteLaborAdapter
  Set PARTS_ADAPTER_TYPE=remote in .env to use RemotePartsAdapter
  Set VENDOR_WORLDPAC_ADAPTER_TYPE=remote in .env to use RemoteVendorAdapter
"""

import logging
from typing import Optional, List
from decimal import Decimal

from app.adapters.labor_adapter_interface import LaborAdapterInterface, LaborTimeResult
from app.adapters.parts_adapter_interface import PartsAdapterInterface, PartResult
from app.adapters.vendor_adapter_interface import VendorAdapterInterface, VendorPriceResult
from app.utils.scraper_client import scraper_client

logger = logging.getLogger(__name__)


class RemoteLaborAdapter(LaborAdapterInterface):
    """
    Labor adapter that calls the remote Scraper Service.
    The Scraper Service scrapes ALLDATA via Chrome CDP.
    """
    
    async def get_labor_time(self, vin: str, job_description: str) -> Optional[LaborTimeResult]:
        logger.info(f"REMOTE LABOR: Requesting from Scraper Service for VIN={vin}")
        
        result = await scraper_client.get_labor_time(vin, job_description)
        
        if result.get("success"):
            return LaborTimeResult(
                jobDescription=job_description,
                laborHours=Decimal(str(result.get("labor_hours", 1.5))),
                source=result.get("source", "remote-scraper"),
                category="Remote Scraped",
                difficulty="Medium"
            )
        else:
            # Return fallback with warning
            logger.warning(f"REMOTE LABOR: Scraper failed - {result.get('error')}")
            return LaborTimeResult(
                jobDescription=f"{job_description} (⚠️ Scraper Service Error)",
                laborHours=Decimal("1.5"),
                source="fallback",
                category="Estimated",
                difficulty="Unknown"
            )


class RemotePartsAdapter(PartsAdapterInterface):
    """
    Parts adapter that calls the remote Scraper Service.
    The Scraper Service scrapes PartsLink24 via Chrome CDP.
    """
    
    async def search_parts(self, vin: str, job_description: str) -> List[PartResult]:
        logger.info(f"REMOTE PARTS: Requesting from Scraper Service for VIN={vin}")
        
        result = await scraper_client.get_parts(vin, job_description)
        
        if result.get("success"):
            parts = []
            for p in result.get("parts", []):
                parts.append(PartResult(
                    partNumber=p.get("part_number", "UNKNOWN"),
                    description=p.get("description", job_description),
                    manufacturer=p.get("manufacturer", "OEM"),
                    price=Decimal("0.00"),
                    isOEM=p.get("is_oem", True),
                    category="Remote Scraped"
                ))
            return parts if parts else [self._fallback_part(job_description)]
        else:
            logger.warning(f"REMOTE PARTS: Scraper failed - {result.get('error')}")
            return [self._fallback_part(job_description)]
    
    def _fallback_part(self, job_description: str) -> PartResult:
        return PartResult(
            partNumber="MANUAL-LOOKUP",
            description=f"{job_description} (⚠️ Scraper Service Error)",
            manufacturer="Unknown",
            price=Decimal("0.00"),
            isOEM=True,
            category="Needs Manual Lookup"
        )


class RemoteVendorAdapter(VendorAdapterInterface):
    """
    Vendor pricing adapter that calls the remote Scraper Service.
    The Scraper Service scrapes Worldpac/SSF via Chrome CDP.
    """
    
    async def get_prices(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        logger.info(f"REMOTE VENDOR: Requesting prices for {part_numbers}")
        
        result = await scraper_client.get_pricing(part_numbers)
        
        if result.get("success"):
            prices = []
            for p in result.get("prices", []):
                prices.append(VendorPriceResult(
                    vendor_id=f"remote_{p.get('vendor', 'unknown')}",
                    vendor_name=p.get("vendor", "Unknown Vendor"),
                    brand=p.get("brand", "Aftermarket"),
                    part_number=p.get("part_number", ""),
                    price=Decimal(str(p.get("price", 0))),
                    stock_status=p.get("stock_status", "Check Stock"),
                    stock_quantity=1,
                    warehouse_location=p.get("warehouse", "Remote"),
                    warehouse_distance_miles=0,
                    delivery_option="Check Vendor",
                    warranty="Manufacturer"
                ))
            return prices if prices else self._fallback_prices(part_numbers)
        else:
            logger.warning(f"REMOTE VENDOR: Scraper failed - {result.get('error')}")
            return self._fallback_prices(part_numbers)
    
    def _fallback_prices(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        return [
            VendorPriceResult(
                vendor_id="fallback",
                vendor_name="Manual Check Required",
                brand="Unknown",
                part_number=pn,
                price=Decimal("0.00"),
                stock_status="⚠️ Scraper Service Error",
                stock_quantity=0,
                warehouse_location="Check Vendor Site",
                warehouse_distance_miles=0,
                delivery_option="Manual Check",
                warranty="Unknown"
            )
            for pn in part_numbers
        ]
