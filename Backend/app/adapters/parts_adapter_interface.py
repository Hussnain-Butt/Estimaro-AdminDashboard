"""
Parts Adapter Interface

Abstract interface for parts lookup services.
This allows easy switching between mock and real implementations (PartsLink24).
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal


class PartResult(BaseModel):
    """Result from parts lookup"""
    partNumber: str = Field(..., description="Part number")
    description: str = Field(..., description="Part description")
    manufacturer: Optional[str] = Field(None, description="Manufacturer/Brand")
    price: Optional[Decimal] = Field(None, description="Estimated price")
    isOEM: bool = Field(default=False, description="Is OEM part")
    category: Optional[str] = Field(None, description="Part category")
    
    class Config:
        json_schema_extra = {
            "example": {
                "partNumber": "45022-SDA-A00",
                "description": "Brake Pad Set - Front",
                "manufacturer": "Honda",
                "price": "85.00",
                "isOEM": True,
                "category": "Brakes"
            }
        }


class PartsAdapterInterface(ABC):
    """Abstract interface for parts lookup adapters"""
    
    @abstractmethod
    async def search_parts(
        self,
        vin: str,
        job_description: str
    ) -> List[PartResult]:
        """
        Search for parts based on VIN and job description.
        
        Args:
            vin: Vehicle Identification Number
            job_description: Description of the job/repair
            
        Returns:
            List of matching parts
        """
        pass
