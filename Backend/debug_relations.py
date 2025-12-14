
import asyncio
import os
import sys
from beanie import init_beanie, PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient

# Add current directory to path
sys.path.append(os.getcwd())

from app.models.estimate import Estimate
from app.models.vehicle import Vehicle
from app.models.customer import Customer
from app.core.config import settings
from app.repositories.estimate_repository import EstimateRepository

async def main():
    print("Connecting to DB...")
    client = AsyncIOMotorClient(settings.DATABASE_URL)
    db = client.get_database()
    await init_beanie(database=db, document_models=[Estimate, Vehicle, Customer])
    
    repo = EstimateRepository()
    
    # Get all estimates
    estimates = await Estimate.find_all().to_list()
    print(f"\nFound {len(estimates)} estimates.")

    for i, estimate in enumerate(estimates):
        print(f"\n--- Estimate #{i+1} [ID: {estimate.id}] ---")
        print(f"Stored Vehicle ID: {estimate.vehicle_id}")
        print(f"Initial Vehicle Obj: {estimate.vehicle}")
        
        # Test populate relations
        try:
            await repo._populate_relations(estimate)
            print(f"Populated Vehicle Obj: {estimate.vehicle}")
            if estimate.vehicle:
                print(f"  Vehicle Details: {estimate.vehicle.year} {estimate.vehicle.make} {estimate.vehicle.model}")
                print(f"  Populated Vehicle.Customer: {estimate.vehicle.customer}")
                if estimate.vehicle.customer:
                     print(f"    Customer Name: {estimate.vehicle.customer.first_name} {estimate.vehicle.customer.last_name}")
            else:
                print("  -> FAILURE: Vehicle not populated.")
        except Exception as e:
            print(f"  -> EXCEPTION in _populate_relations: {e}")

if __name__ == "__main__":
    asyncio.run(main())
