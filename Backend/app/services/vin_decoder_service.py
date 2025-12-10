"""
VIN Decoder Service - NHTSA API Integration

Uses the free NHTSA (National Highway Traffic Safety Administration) API
to decode VIN and retrieve vehicle information.

API Documentation: https://vpic.nhtsa.dot.gov/api/
"""
import httpx
from typing import Optional, Dict
from pydantic import BaseModel, Field


class VehicleDecodeResult(BaseModel):
    """Result from VIN decode operation"""
    vin: str
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None
    manufacturer: Optional[str] = None
    vehicleType: Optional[str] = None
    bodyClass: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "vin": "1HGBH41JXMN109186",
                "year": 2021,
                "make": "HONDA",
                "model": "Accord",
                "trim": "EX-L",
                "engine": "2.0L L4 DOHC 16V TURBO",
                "manufacturer": "HONDA",
                "vehicleType": "PASSENGER CAR",
                "bodyClass": "Sedan/Saloon"
            }
        }


class VINDecoderService:
    """Service for decoding VINs using NHTSA API"""
    
    NHTSA_API_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"
    
    async def decode_vin(self, vin: str) -> VehicleDecodeResult:
        """
        Decode VIN using NHTSA API.
        
        Args:
            vin: Vehicle Identification Number (17 characters)
            
        Returns:
            Decoded vehicle information
            
        Raises:
            ValueError: If VIN is invalid
            httpx.HTTPError: If API request fails
        """
        # Validate VIN format
        if not vin or len(vin) != 17:
            raise ValueError("VIN must be exactly 17 characters")
        
        # Make API request
        url = self.NHTSA_API_URL.format(vin=vin.upper())
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        
        # Parse response
        return self._parse_nhtsa_response(vin, data)
    
    def _parse_nhtsa_response(self, vin: str, data: Dict) -> VehicleDecodeResult:
        """
        Parse NHTSA API response.
        
        NHTSA returns data in format:
        {
            "Results": [
                {"Variable": "Make", "Value": "HONDA"},
                {"Variable": "Model", "Value": "Accord"},
                ...
            ]
        }
        """
        results = data.get("Results", [])
        
        # Create a dictionary for easy lookup
        vehicle_data = {
            item["Variable"]: item["Value"] 
            for item in results 
            if item.get("Value") and item["Value"] != "Not Applicable"
        }
        
        # Extract relevant fields
        year_str = vehicle_data.get("Model Year")
        year = int(year_str) if year_str and year_str.isdigit() else None
        
        return VehicleDecodeResult(
            vin=vin,
            year=year,
            make=vehicle_data.get("Make"),
            model=vehicle_data.get("Model"),
            trim=vehicle_data.get("Trim"),
            engine=vehicle_data.get("Engine Model") or vehicle_data.get("Engine Configuration"),
            manufacturer=vehicle_data.get("Manufacturer Name"),
            vehicleType=vehicle_data.get("Vehicle Type"),
            bodyClass=vehicle_data.get("Body Class")
        )


# Singleton instance
vin_decoder_service = VINDecoderService()
