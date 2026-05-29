"""Entry point - runs a single end-to-end test estimate.
Later this will become the worker that polls the backend for jobs."""
import asyncio
import json
from loguru import logger

from core.hermes_client import HermesClient
from services.nhtsa_service import decode_vin
from models.job_spec import JobSpec
from agents.alldata_agent import lookup_labor_time


SAMPLE_COMPLAINT = "2018 Honda Civic making grinding noise from front when braking at low speeds"
SAMPLE_VIN = "2HGFC2F59JH123456"


async def run_pipeline(complaint: str, vin: str):
    print("\n=== STAGE 1: Parse complaint with Hermes ===")
    hermes = HermesClient()
    job_dict = hermes.parse_job_spec(complaint, vin)
    print(json.dumps(job_dict, indent=2))
    job = JobSpec(**job_dict)

    print("\n=== STAGE 2: Decode VIN ===")
    vehicle = await decode_vin(vin)
    print(f"{vehicle.year} {vehicle.make} {vehicle.model} {vehicle.trim or ''}")
    print(f"Engine: {vehicle.engine}")

    print("\n=== STAGE 3: ALLDATA labor lookup ===")
    labor, meta = await lookup_labor_time(job, vehicle)

    print("\n=== FINAL RESULT ===")
    if labor:
        print(labor.model_dump_json(indent=2))
        print(f"\nVerification: {meta.get('verification')}")
    else:
        print("Labor not found. See screenshots/ for trace.")
        print(f"History: {len(meta.get('agent_run', {}).get('history', []))} steps")


if __name__ == "__main__":
    asyncio.run(run_pipeline(SAMPLE_COMPLAINT, SAMPLE_VIN))
