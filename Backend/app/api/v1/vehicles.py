"""
Vehicles API Routes

Endpoints for vehicle-related operations:
- GET /decode/{vin} - Decode VIN using NHTSA API
"""
from fastapi import APIRouter, HTTPException, status
from app.services.vin_decoder_service import vin_decoder_service, VehicleDecodeResult

router = APIRouter()


@router.get(
    "/decode/{vin}",
    response_model=VehicleDecodeResult,
    summary="Decode VIN",
    description="Decode Vehicle Identification Number using NHTSA free API to get vehicle details."
)
async def decode_vin(vin: str):
    """
    Decode VIN using NHTSA API.
    
    **Free API** - No authentication required.
    
    **Returns:**
    - VIN
    - Year, Make, Model, Trim
    - Engine information
    - Manufacturer
    - Vehicle type and body class
    
    **Example VINs to try:**
    - `1HGBH41JXMN109186` - Honda Accord
    - `1FTFW1ET5BFC10628` - Ford F-150
    - `5YJSA1E14HF177003` - Tesla Model S
    """
    try:
        result = await vin_decoder_service.decode_vin(vin)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decode VIN: {str(e)}"
        )
