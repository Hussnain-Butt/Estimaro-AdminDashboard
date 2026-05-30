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
    import logging, traceback
    log = logging.getLogger(__name__)

    client = AsyncIOMotorClient(settings.DATABASE_URL)

    # get_default_database() raises ConfigurationError when no /dbname is
    # present in the URI (common on Railway where the env var is a bare
    # cluster URI without a database path).  Fall back so Beanie always inits.
    try:
        db_name = client.get_default_database().name
        if not db_name or db_name == "test":
            db_name = "estimaro_db"
    except Exception:
        db_name = "estimaro_db"
    log.info(f"Using database: {db_name}")

    from app.models.estimate import Estimate
    from app.models.customer import Customer
    from app.models.vehicle import Vehicle
    from app.models.user import User
    from app.models.shop_settings import ShopSettings

    try:
        from app.models.auto_gen_job import AutoGenJob
        log.info(f"AutoGenJob imported OK: {AutoGenJob}")
    except Exception as e:
        log.error(f"FAILED to import AutoGenJob: {e}\n{traceback.format_exc()}")
        AutoGenJob = None

    models = [User, Customer, Vehicle, Estimate, ShopSettings]
    if AutoGenJob is not None:
        models.append(AutoGenJob)

    try:
        await init_beanie(database=client[db_name], document_models=models)
        log.info(f"init_beanie OK with {len(models)} models")
    except Exception as e:
        log.error(f"init_beanie FAILED: {e}\n{traceback.format_exc()}")
        # Fallback: try without AutoGenJob so the rest of the app keeps working
        if AutoGenJob is not None:
            log.warning("Retrying init_beanie without AutoGenJob")
            await init_beanie(database=client[db_name], document_models=[User, Customer, Vehicle, Estimate, ShopSettings])
        raise

# Simplified dependency for backward compatibility during migration
# In purely async Beanie, we don't strictly need a session dependency like SQLAlchemy
# but we might need to mock it or remove it from routes.
def get_db():
    """Deprecated: No-op for MongoDB migration"""
    yield None

