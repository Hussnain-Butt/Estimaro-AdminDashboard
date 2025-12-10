"""
Labor Adapter Interface

Abstract interface for labor time lookup services.
This allows easy switching between mock and real implementations (ALLDATA).
"""
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, Field
from decimal import Decimal


class LaborTimeResult(BaseModel):
    """Result from labor time lookup"""
    jobDescription: str = Field(..., description="Job description")
    laborHours: Decimal = Field(..., description="Standard labor hours")
    source: str = Field(..., description="Data source (mock/alldata)")
    category: Optional[str] = Field(None, description="Job category")
    difficulty: Optional[str] = Field(None, description="Difficulty level")
    
    class Config:
        json_schema_extra = {
            "example": {
                "jobDescription": "Brake Pad Replacement - Front",
                "laborHours": "1.5",
                "source": "mock",
                "category": "Brakes",
                "difficulty": "Medium"
            }
        }


class LaborAdapterInterface(ABC):
    """Abstract interface for labor time adapters"""
    
    @abstractmethod
    async def get_labor_time(
        self,
        vin: str,
        job_description: str
    ) -> Optional[LaborTimeResult]:
        """
        Get labor time for a specific job.
        
        Args:
            vin: Vehicle Identification Number
            job_description: Description of the job
            
        Returns:
            Labor time result or None if not found
        """
        pass
