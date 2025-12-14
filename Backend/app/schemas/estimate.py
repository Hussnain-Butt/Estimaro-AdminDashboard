from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# ============================================================================
# Vehicle Schemas (matching frontend VehicleInfo)
# ============================================================================

class VehicleInfoSchema(BaseModel):
    """Vehicle information schema matching frontend formData.vehicleInfo"""
    vin: str = Field(..., description="Vehicle Identification Number")
    year: Optional[int] = Field(None, description="Vehicle year")
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    trim: Optional[str] = Field(None, description="Vehicle trim")
    engine: Optional[str] = Field(None, description="Engine type")
    mileage: Optional[int] = Field(None, description="Current mileage")

    class Config:
        json_schema_extra = {
            "example": {
                "vin": "1HGBH41JXMN109186",
                "year": 2021,
                "make": "Honda",
                "model": "Accord",
                "trim": "EX-L",
                "engine": "2.0L Turbo",
                "mileage": 45000
            }
        }


# ============================================================================
# Customer Schemas (matching frontend CustomerInfo)
# ============================================================================

class CustomerInfoSchema(BaseModel):
    """Customer information schema matching frontend formData.customerInfo"""
    firstName: str = Field(..., description="Customer first name")
    lastName: str = Field(..., description="Customer last name")
    email: Optional[str] = Field(None, description="Customer email address")
    phone: str = Field(..., description="Customer phone number")

    class Config:
        json_schema_extra = {
            "example": {
                "firstName": "John",
                "lastName": "Doe",
                "email": "john.doe@example.com",
                "phone": "+1-555-123-4567"
            }
        }


# ============================================================================
# Labor Item Schemas (matching frontend LaborItem)
# ============================================================================

class LaborItemSchema(BaseModel):
    """Labor item schema matching frontend formData.laborItems[]"""
    id: Optional[str] = Field(None, description="Temporary frontend ID")
    description: str = Field(..., min_length=1, max_length=500, description="Labor description")
    hours: float = Field(..., ge=0, description="Labor hours")
    rate: float = Field(..., ge=0, description="Hourly rate")
    total: float = Field(..., ge=0, description="Total labor cost (hours * rate)")

# ... (PartItemSchema)
class PartItemSchema(BaseModel):
    """Part item schema matching frontend formData.partsItems[]"""
    id: Optional[str] = Field(None, description="Temporary frontend ID")
    description: str = Field(..., min_length=1, max_length=500, description="Part description")
    partNumber: Optional[str] = Field(None, max_length=100, description="Part number")
    quantity: float = Field(..., ge=0, description="Quantity")
    cost: float = Field(..., ge=0, description="Unit cost")
    markup: float = Field(default=0.0, ge=0, le=100, description="Markup percentage")
    total: float = Field(..., ge=0, description="Total part cost")
    vendor: Optional[str] = Field(None, max_length=100, description="Vendor name")
    reason_badge: Optional[str] = Field(None, description="Reason for auto-added item")

# ============================================================================
# Estimate Request Schemas
# ============================================================================

class EstimateCreateSchema(BaseModel):
    """
    Complete estimate creation schema matching frontend formData structure.
    This is used when creating a new estimate.
    """
    vehicleInfo: VehicleInfoSchema
    customerInfo: CustomerInfoSchema
    serviceRequest: Optional[str] = Field(None, max_length=2000, description="Service request description")
    laborItems: List[LaborItemSchema] = Field(default_factory=list, description="List of labor items")
    partsItems: List[PartItemSchema] = Field(default_factory=list, description="List of parts items")

    class Config:
        json_schema_extra = {
            "example": {
                "vehicleInfo": {
                    "vin": "1HGBH41JXMN109186",
                    "year": 2021,
                    "make": "Honda",
                    "model": "Accord",
                    "mileage": 45000
                },
                "customerInfo": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1-555-123-4567"
                },
                "serviceRequest": "Customer reports squeaking noise when braking",
                "laborItems": [
                    {
                        "description": "Brake Pad Replacement",
                        "hours": 1.5,
                        "rate": 120.00,
                        "total": 180.00
                    }
                ],
                "partsItems": [
                    {
                        "description": "Brake Pad Set - Front",
                        "partNumber": "BRK-12345",
                        "quantity": 1.0,
                        "cost": 85.00,
                        "markup": 30.0,
                        "total": 110.50
                    }
                ]
            }
        }


class CalculationRequestSchema(BaseModel):
    """
    Schema for real-time calculation requests (no customer info needed).
    Used for the /estimates/calculate endpoint.
    """
    laborItems: List[LaborItemSchema] = Field(default_factory=list)
    partsItems: List[PartItemSchema] = Field(default_factory=list)
    taxRate: Optional[float] = Field(None, ge=0, le=1, description="Tax rate (0.08 = 8%)")


# ============================================================================
# Estimate Response Schemas
# ============================================================================

class CleaningKitSchema(BaseModel):
    """Cleaning kit information (replaces shop fees)"""
    name: str = Field(..., description="Cleaning kit name")
    includes: Optional[List[str]] = Field(None, description="Items included in kit")
    price: float = Field(..., description="Cleaning kit price")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Brake Service Cleaning Kit",
                "includes": ["Brake cleaner", "Caliper grease", "Disposable gloves"],
                "price": 15.00
            }
        }


# ... (CalculationBreakdownSchema)
class CalculationBreakdownSchema(BaseModel):
    """Breakdown of calculation results"""
    laborTotal: float = Field(..., description="Total labor cost")
    partsTotal: float = Field(..., description="Total parts cost")
    subtotal: float = Field(..., description="Subtotal before tax")
    taxAmount: float = Field(..., description="Tax amount")
    cleaningKit: Optional[CleaningKitSchema] = Field(None, description="Service cleaning kit (replaces shop fees)")
    total: float = Field(..., description="Grand total")

    class Config:
        json_schema_extra = {
            "example": {
                "laborTotal": "180.00",
                "partsTotal": "110.50",
                "subtotal": "290.50",
                "taxAmount": "23.24",
                "total": "313.74"
            }
        }


class CalculationResponseSchema(BaseModel):
    """Response schema for calculation endpoint"""
    breakdown: CalculationBreakdownSchema
    taxRate: float = Field(..., description="Tax rate used")

    class Config:
        json_schema_extra = {
            "example": {
                "breakdown": {
                    "laborTotal": "180.00",
                    "partsTotal": "110.50",
                    "subtotal": "290.50",
                    "taxAmount": "23.24",
                    "total": "313.74"
                },
                "taxRate": "0.08"
            }
        }


class EstimateResponseSchema(BaseModel):
    """Response schema for estimate creation/retrieval"""
    estimateId: str = Field(..., description="Estimate ID")
    status: str = Field(..., description="Estimate status")
    publicToken: str = Field(..., description="Public token for customer portal")
    vehicleInfo: VehicleInfoSchema
    customerInfo: CustomerInfoSchema
    serviceRequest: Optional[str]
    laborItems: List[LaborItemSchema]
    partsItems: List[PartItemSchema]
    breakdown: CalculationBreakdownSchema
    createdAt: datetime
    updatedAt: datetime
    expiresAt: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "estimateId": 1,
                "status": "draft",
                "publicToken": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "vehicleInfo": {
                    "vin": "1HGBH41JXMN109186",
                    "year": 2021,
                    "make": "Honda",
                    "model": "Accord"
                },
                "customerInfo": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1-555-123-4567"
                },
                "serviceRequest": "Brake service",
                "laborItems": [],
                "partsItems": [],
                "breakdown": {
                    "laborTotal": "180.00",
                    "partsTotal": "110.50",
                    "subtotal": "290.50",
                    "taxAmount": "23.24",
                    "total": "313.74"
                },
                "createdAt": "2025-12-10T19:00:00Z",
                "updatedAt": "2025-12-10T19:00:00Z"
            }
        }
