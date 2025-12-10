"""
Database models package.
Import all models here for Alembic auto-detection.
"""
from app.models.user import User, UserRole
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.estimate import Estimate, EstimateStatus
from app.models.estimate_item import EstimateItem, ItemType

__all__ = [
    "User",
    "UserRole",
    "Customer",
    "Vehicle",
    "Estimate",
    "EstimateStatus",
    "EstimateItem",
    "ItemType",
]
