"""PartsLink24 OEM parts-catalog agent.

PartsLink24 is the genuine-OEM EPC for European brands (Audi, BMW, Mercedes,
VW, MINI, Bentley, Jaguar/Land Rover, ...). Given a VIN it resolves the exact
vehicle and lets us navigate the parts catalogue to read OEM part numbers and
list prices.

Role in the pipeline: confirm/enrich the OEM part numbers ALLDATA produced and
attach the OEM list price, returned as uniform VendorQuote rows.
"""
import json as _json
from typing import Optional, Tuple

from loguru import logger

from models.job_spec import JobSpec, VehicleFingerprint, VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "PartsLink24"
PORTAL_URL = "https://www.partslink24.com/partslink24/user/brandMenu.do"

# European marques PartsLink24 actually covers. Used to skip the portal fast
# for vehicles it can never serve (domestic/Asian) instead of wasting a run.
SUPPORTED_MAKES = {
    "audi", "bentley", "bmw", "mini", "jaguar", "land rover", "landrover",
    "mercedes", "mercedes-benz", "volkswagen", "vw", "man", "porsche", "seat", "skoda",
}


def supports(vehicle: VehicleFingerprint) -> bool:
    return (vehicle.make or "").strip().lower() in SUPPORTED_MAKES


def _build_task(job: JobSpec, vehicle: VehicleFingerprint, target_parts: list[dict]) -> str:
    wanted = "\n".join(
        f"      - {p.get('name','?')}  (OEM# {p.get('oem_number') or 'unknown'})"
        for p in (target_parts or [])
    ) or "      - (no specific OEM numbers from ALLDATA; use the symptom)"

    return f"""
You are inside the PartsLink24 OEM parts catalogue. The shop is already logged in.

VEHICLE:
  Year:  {vehicle.year}
  Make:  {vehicle.make}
  Model: {vehicle.model}
  VIN:   {vehicle.vin}

CUSTOMER JOB:
  System:    {job.system}
  Subsystem: {job.subsystem}
  Symptom:   {job.symptom}

PARTS WE WANT PRICES FOR (from ALLDATA):
{wanted}

GOAL: Find these OEM parts in the PartsLink24 catalogue for THIS vehicle and read
their genuine OEM part number and list price.

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. Find the "Search VIN" text box, type the VIN exactly, then click GO.
  2. If a brand must be chosen, pick the brand that matches {vehicle.make}.
  3. Wait for the vehicle to resolve (year/make/model should appear).
  4. Open the parts catalogue tree and navigate to the assembly group matching
     the symptom:
       - brakes / pads / rotors -> Brake system -> Front (or Rear) brake / Disc brake
       - oil / lubrication      -> Engine -> Lubrication / Oil filter
       - suspension / steering  -> Front axle / Suspension
       - ignition / spark plug  -> Engine -> Ignition
  5. On the parts illustration / list page you will see rows with a PART NUMBER,
     a DESCRIPTION and (where shown) a PRICE.
  6. Match the rows to the wanted parts above by description/number.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "matched_vehicle": "<year make model shown on screen>",
    "section": "<catalogue path you took>",
    "parts": [
      {{"name": "<row description>", "oem_number": "<part number>", "price": <number or null>, "brand": "{vehicle.make}"}}
    ]
  }}
Then action="done".

CRITICAL RULES:
  * Only report parts visible on the SAME catalogue page for THIS vehicle.
  * If a price is not shown, use null (do NOT invent one).
  * If the VIN does not resolve or the catalogue cannot be reached, confidence < 0.6
    and action="ask_human" describing exactly what blocked you.
"""


async def lookup(
    job: JobSpec,
    vehicle: VehicleFingerprint,
    target_parts: list[dict],
    *,
    max_steps: int = 25,
    timeout: int = 300,
) -> Tuple[list[VendorQuote], dict]:
    """Returns (quotes, meta). One VendorQuote per part the agent located."""
    if not supports(vehicle):
        return [], {"skipped": f"{vehicle.make} not covered by PartsLink24"}

    task = _build_task(job, vehicle, target_parts)
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps, timeout=timeout)
    if raw is None:
        return [], meta

    quotes: list[VendorQuote] = []
    section = raw.get("section") or ""
    screenshot = None
    try:
        hist = meta.get("history") or []
        bs = meta.get("best_step")
        if bs is not None and bs < len(hist):
            screenshot = hist[bs].get("screenshot")
    except Exception:
        pass

    for p in (raw.get("parts") or []):
        try:
            price = p.get("price")
            price = float(price) if price not in (None, "", "null") else None
        except (TypeError, ValueError):
            price = None
        quotes.append(VendorQuote(
            vendor=PORTAL_NAME,
            requested_part=str(p.get("oem_number") or p.get("name") or ""),
            matched_part_name=p.get("name"),
            oem_number=p.get("oem_number") or None,
            brand=p.get("brand") or vehicle.make,
            price=price,
            list_price=price,
            in_stock=None,
            availability=None,
            found=True,
            note=None,
            screenshot_path=screenshot,
        ))

    meta["section_path"] = section
    logger.info(f"[{PORTAL_NAME}] extracted {len(quotes)} part(s); section={section!r}")
    return quotes, meta


if __name__ == "__main__":
    import asyncio
    from models.job_spec import JobSpec, VehicleFingerprint

    sample_job = JobSpec(
        system="braking", subsystem="front_brakes",
        symptom="front brake pads worn / grinding", severity="medium",
        keywords=["brake pad", "front"],
    )
    # Use a REAL VIN of a covered marque when running this on the VPS.
    sample_vehicle = VehicleFingerprint(
        vin="WAUEFAFL1DA000000", year=2013, make="Audi", model="A4",
    )
    target = [{"name": "Front Pads", "oem_number": None}]
    quotes, meta = asyncio.run(lookup(sample_job, sample_vehicle, target))
    print("\n=== QUOTES ===")
    for q in quotes:
        print(q.model_dump_json(indent=2))
    print("\n=== META ===")
    print({k: v for k, v in meta.items() if k != "history"})
