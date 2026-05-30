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

THE VEHICLE IS IDENTIFIED BY ITS VIN — PartsLink24 will resolve the exact year,
model and chassis from the VIN itself. Do NOT rely on any pre-known year/model
and do NOT abort over a year mismatch; trust whatever PartsLink24 resolves.
  VIN:           {vehicle.vin}
  Likely brand:  {vehicle.make or 'unknown (read it from the VIN result)'}

CUSTOMER JOB:
  System:    {job.system}
  Subsystem: {job.subsystem}
  Symptom:   {job.symptom}

PARTS WE WANT PRICES FOR (from ALLDATA):
{wanted}

GOAL: Resolve the vehicle from the VIN, navigate to the assembly group matching
the symptom, and read each genuine OEM part number + list price.

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. On the brand menu: type the VIN into the "Search VIN" box, click GO.
  2. Pick the brand. Use the plain marque (e.g. "Mercedes-Benz", "Audi", "BMW")
     for normal vehicles. ONLY if the catalogue says the vehicle is not found,
     go back and try the "<Brand> Classic" entry (older/classic chassis live there).
  3. The brand catalogue app opens. If no specific vehicle/model is selected yet
     (model grid is empty), find the "Direct entry" search box at the TOP of the
     brand app, type the VIN there, and press the search (magnifier) icon. This
     resolves the exact vehicle inside the catalogue.
  4. Once the vehicle is resolved, open the assembly-group tree and navigate to
     the subsystem matching the symptom:
       - brakes / pads / rotors -> Brake system -> Front (or Rear) brake / Disc brake
       - oil / lubrication      -> Engine -> Lubrication / Oil filter
       - suspension / steering  -> Front axle / Suspension
       - ignition / spark plug  -> Engine -> Ignition
  5. On the parts illustration / list page you will see rows with a PART NUMBER,
     a DESCRIPTION and (where shown) a PRICE. Match them to the wanted parts.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "matched_vehicle": "<the vehicle text PartsLink24 shows>",
    "section": "<catalogue path you took>",
    "parts": [
      {{"name": "<row description>", "oem_number": "<part number>", "price": <number or null>, "brand": "{vehicle.make or 'OEM'}"}}
    ]
  }}
Then action="done".

CRITICAL RULES:
  * The VIN is the source of truth. Never abort because a year/model differs from
    any expectation — there is no expectation, only what PartsLink24 shows.
  * Only report parts visible on the SAME catalogue page for THIS vehicle.
  * If a price is not shown, use null (do NOT invent one). Many catalogues show
    part numbers without prices — that is fine, still extract the numbers.
  * Only use action="ask_human" if you truly cannot resolve the VIN after trying
    both the brand menu VIN box AND the in-catalogue "Direct entry" box.
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
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal="partslink24")
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
