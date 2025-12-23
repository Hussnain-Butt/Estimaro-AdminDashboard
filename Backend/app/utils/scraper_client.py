"""
Scraper Service Client

This module provides a client to communicate with the Scraper Microservice
running on the Windows RDP server.

The Scraper Service handles all vendor website scraping via Chrome CDP.
"""

import logging
import httpx
from typing import Optional, List, Dict
from pydantic import BaseModel
from app.core.config import settings

logger = logging.getLogger(__name__)


class ScraperClient:
    """Client for communicating with Scraper Microservice"""
    
    def __init__(self):
        # Get config from environment
        self.base_url = getattr(settings, 'SCRAPER_SERVICE_URL', 'http://localhost:5000')
        self.api_key = getattr(settings, 'SCRAPER_API_KEY', 'estimaro_scraper_secret_2024')
        self.timeout = 60.0  # 60 seconds for scraping operations
    
    async def _make_request(self, endpoint: str, data: dict) -> dict:
        """Make authenticated request to Scraper Service"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=data, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            logger.error(f"Cannot connect to Scraper Service at {url}")
            return {"success": False, "error": "Scraper Service not available"}
        except httpx.TimeoutException:
            logger.error(f"Timeout calling Scraper Service: {endpoint}")
            return {"success": False, "error": "Scraper Service timeout"}
        except Exception as e:
            logger.error(f"Scraper Service error: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_labor_time(self, vin: str, job_description: str) -> dict:
        """Get labor time from ALLDATA via Scraper Service"""
        logger.info(f"Calling Scraper Service for labor: VIN={vin}")
        
        return await self._make_request("/scrape/labor", {
            "vin": vin,
            "job_description": job_description
        })
    
    async def get_parts(self, vin: str, job_description: str) -> dict:
        """Get OEM parts from PartsLink24 via Scraper Service"""
        logger.info(f"Calling Scraper Service for parts: VIN={vin}")
        
        return await self._make_request("/scrape/parts", {
            "vin": vin,
            "job_description": job_description
        })
    
    async def get_pricing(self, part_numbers: List[str]) -> dict:
        """Get pricing from vendors via Scraper Service"""
        logger.info(f"Calling Scraper Service for pricing: {part_numbers}")
        
        return await self._make_request("/scrape/pricing", {
            "part_numbers": part_numbers
        })
    
    async def health_check(self) -> dict:
        """Check if Scraper Service is healthy"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.json()
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}


# Singleton instance
scraper_client = ScraperClient()
