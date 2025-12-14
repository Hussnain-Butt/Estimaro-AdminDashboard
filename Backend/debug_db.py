
import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.estimate import Estimate
from app.models.vehicle import Vehicle
from app.models.customer import Customer
from app.core.config import settings

async def main():
    print(f"Connecting to DB: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else 'LOCAL'}") # Mask password
    
    client = AsyncIOMotorClient(settings.DATABASE_URL)
    db = client.get_database() # Get default DB from connection string or name
    print(f"Database Name: {db.name}")
    
    await init_beanie(database=db, document_models=[Estimate, Vehicle, Customer])
    
    estimates = await Estimate.find_all().to_list()
    print(f"\nTotal Estimates: {len(estimates)}")
    
    for est in estimates:
        print(f"ID: {est.id}, Advisor: {est.advisor_id}, Status: {est.status}")
        print(f"  Vehicle ID: {est.vehicle_id}")
        
    if len(estimates) == 0:
        print("\nNo estimates found. Please create one on the frontend first.")

if __name__ == "__main__":
    asyncio.run(main())
