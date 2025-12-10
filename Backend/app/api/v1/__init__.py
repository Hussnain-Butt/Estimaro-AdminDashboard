"""
API v1 Router

Aggregates all v1 API routes.
"""
from fastapi import APIRouter
from app.api.v1 import estimates, public, vehicles, labor, parts, auto_generate

# Create main v1 router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(
    auto_generate.router,
    prefix="/auto",
    tags=["🚀 Auto-Generate - One-Click Estimate"]
)

api_router.include_router(
    estimates.router,
    prefix="/estimates",
    tags=["Estimates"]
)

api_router.include_router(
    public.router,
    prefix="/public",
    tags=["Public - Customer Portal"]
)

api_router.include_router(
    vehicles.router,
    prefix="/vehicles",
    tags=["Vehicles - VIN Decoder"]
)

api_router.include_router(
    labor.router,
    prefix="/labor",
    tags=["Labor - Time Lookup"]
)

api_router.include_router(
    parts.router,
    prefix="/parts",
    tags=["Parts - Search"]
)
