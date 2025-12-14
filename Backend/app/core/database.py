from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings

# Placeholder for models list (will be populated in main.py)
# from app.models.estimate import Estimate
# from app.models.customer import Customer
# from app.models.vehicle import Vehicle
# from app.models.user import User

async def init_db():
    """
    Initialize MongoDB connection and Beanie ODM.
    """
    client = AsyncIOMotorClient(settings.DATABASE_URL)
    
    # Selecting the database name from the URL or default
    db_name = client.get_default_database().name
    if not db_name or db_name == 'test':
         db_name = "estimaro_db"

    # Import models
    from app.models.estimate import Estimate
    from app.models.customer import Customer
    from app.models.vehicle import Vehicle
    from app.models.user import User

    # Initialize Beanie
    await init_beanie(
        database=client[db_name],
        document_models=[
            User,
            Customer,
            Vehicle,
            Estimate
        ]
    )

# Simplified dependency for backward compatibility during migration
# In purely async Beanie, we don't strictly need a session dependency like SQLAlchemy
# but we might need to mock it or remove it from routes.
def get_db():
    """Deprecated: No-op for MongoDB migration"""
    yield None

