"""Customer list endpoint with per-row activity counts.

Each row carries the customer's vehicle count, estimate count, last-visit
date and the cached display name of their most recent vehicle so the
Customers page can render the table + detail panel without follow-up calls.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from app.models.customer import Customer
from app.models.estimate import Estimate
from app.models.vehicle import Vehicle


router = APIRouter()


def _customer_to_row(c: Customer, vehicles: List[Vehicle], estimates: List[Estimate]) -> Dict[str, Any]:
    last_visit: Optional[datetime] = None
    for e in estimates:
        if e.created_at and (last_visit is None or e.created_at > last_visit):
            last_visit = e.created_at
    last_vehicle = vehicles[0] if vehicles else None
    return {
        "_id": str(c.id) if c.id else None,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "email": c.email,
        "phone": c.phone,
        "vehicles_count": len(vehicles),
        "estimates_count": len(estimates),
        "last_visit": last_visit.isoformat() if last_visit else None,
        "primary_vehicle": last_vehicle.display_name if last_vehicle else None,
    }


@router.get(
    "/",
    summary="List customers with activity counts",
    description=(
        "Returns one row per customer enriched with vehicle/estimate counts "
        "and last-visit timestamp. The Customers page renders the table and "
        "detail panel from this single response."
    ),
)
async def list_customers():
    customers = await Customer.find_all().to_list()
    if not customers:
        return []

    customer_ids = [str(c.id) for c in customers]
    all_vehicles = await Vehicle.find(
        {"customer_id": {"$in": customer_ids}}
    ).to_list()
    vehicle_ids_by_customer: Dict[str, List[str]] = {cid: [] for cid in customer_ids}
    vehicles_by_customer: Dict[str, List[Vehicle]] = {cid: [] for cid in customer_ids}
    for v in all_vehicles:
        cid = v.customer_id
        if cid in vehicles_by_customer:
            vehicles_by_customer[cid].append(v)
            if v.id is not None:
                vehicle_ids_by_customer[cid].append(str(v.id))

    flat_vehicle_ids = [vid for ids in vehicle_ids_by_customer.values() for vid in ids]
    all_estimates: List[Estimate] = []
    if flat_vehicle_ids:
        all_estimates = await Estimate.find(
            {"vehicle_id": {"$in": flat_vehicle_ids}}
        ).to_list()
    estimates_by_customer: Dict[str, List[Estimate]] = {cid: [] for cid in customer_ids}
    for est in all_estimates:
        for cid, vids in vehicle_ids_by_customer.items():
            if est.vehicle_id in vids:
                estimates_by_customer[cid].append(est)
                break

    rows = [
        _customer_to_row(
            c,
            sorted(vehicles_by_customer[str(c.id)], key=lambda v: v.created_at or datetime.min, reverse=True),
            estimates_by_customer[str(c.id)],
        )
        for c in customers
    ]
    rows.sort(key=lambda r: r["last_visit"] or "", reverse=True)
    return rows
