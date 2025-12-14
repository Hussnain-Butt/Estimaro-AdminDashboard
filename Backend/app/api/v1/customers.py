from fastapi import APIRouter, HTTPException
from typing import List
from app.models.customer import Customer

router = APIRouter()

@router.get("/", response_model=List[Customer])
async def get_customers():
    """
    Get all customers.
    """
    customers = await Customer.find_all().to_list()
    return customers
