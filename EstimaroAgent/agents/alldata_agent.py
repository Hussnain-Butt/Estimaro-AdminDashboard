"""ALLDATA labor-time + parts agent (DOM-aware redesign v2).

Strategy:
  1. Hybrid entry: go directly to the ALLDATA Repair portal (logged-in).
  2. Vision-driven navigation: Year/Make/Model -> Subsystem -> Operation page.
  3. Per-operation page yields BOTH labor hours AND OEM parts (number + price).
  4. Hermes verifies extraction matches the customer complaint.
"""
import asyncio
import json as _json
from loguru import logger
from agents.base_agent import VisionAgent
from core.browser import ChromeDebugBrowser
from models.job_spec import JobSpec, VehicleFingerprint, LaborResult, PartResult
from services.verification import verify_with_hermes


ALLDATA_HOME = "https://my.alldata.com/migrate/#/home"


def _build_task(job: JobSpec, vehicle: VehicleFingerprint) -> str:
    return f"""
You are inside the ALLDATA Repair portal. The shop is already logged in.

VEHICLE:
  Year:    {vehicle.year}
  Make:    {vehicle.make}
  Model:   {vehicle.model}
  Trim:    {vehicle.trim or 'any'}
  Engine:  {vehicle.engine or 'any'}
  VIN:     {vehicle.vin}

CUSTOMER JOB:
  System:    {job.system}
  Subsystem: {job.subsystem}
  Symptom:   {job.symptom}
  Keywords:  {', '.join(job.keywords)}

GOAL: On the ALLDATA "Parts and Labor" article page for the operation that best
matches the customer symptom, extract BOTH labor hours AND OEM parts.

NAVIGATION PLAN (use numbered overlays in screenshots):
  1. If you see REPAIR / ESTIMATOR tiles, click REPAIR.
  2. Pick the vehicle (Year/Make/Model/Engine) — VERIFY it matches the spec above.
  3. Navigate the category tree to the SPECIFIC subsystem matching the symptom.
     - For brakes:    Brakes and Traction Control -> Disc Brake System -> Brake Pad (front pads complaint)
                                                                       -> Brake Rotor (rotor complaint)
     - For engine oil: Engine, Cooling and Exhaust -> Lubrication System
     - For transmission: Transmission and Drivetrain -> Automatic Transmission
     - For suspension: Suspension and Steering
     - For ignition/plugs: Engine -> Ignition System -> Spark Plug
     - For battery/starter: Starting and Charging
     - For cooling/coolant: Engine -> Cooling System
  4. From the component page, click the "P" (Parts and Labor) cell, NOT "R" (Repair text).
  5. On the Parts and Labor article page you will see two tables:
       Parts table:  columns OEM PART #, PRICE, QUANTITY
       Labor table:  columns SKILL, WARRANTY, STANDARD, HOURS (Remove & Replace section)
  6. Pick the labor row that best matches symptom + subsystem (e.g. "Front Pads" for front brake grinding).
  7. Use action="extract" with value as a JSON STRING of this exact schema:
       {{
         "operation": "<labor row name, e.g. Front Pads>",
         "hours": <STANDARD column number>,
         "skill": "<A|B|C if shown>",
         "matched_vehicle": "<year make model engine displayed at top>",
         "section": "<breadcrumb path you took, e.g. Vehicle > Brakes > Disc Brake System > Brake Pad>",
         "parts": [
            {{"name": "Front Pads", "oem_number": "45022TBAA00", "price": 77.65, "qty": 1}},
            {{"name": "Rear Pads", "oem_number": "43022TBAA02", "price": 0.00, "qty": 1}}
         ]
       }}
     Only include parts visible on the SAME Parts and Labor page (not from other components).
     If a price shows 0.00, set price to 0.0 (still include).
  8. action="done" right after extracting.

CRITICAL RULES:
  * DO NOT pick the first row blindly. Match operation to the symptom precisely.
  * If multiple labor rows match (e.g. Front Pads vs Rear Pads), pick by symptom location.
  * Confidence < 0.6 -> action="ask_human" instead of extracting.
  * If vehicle on screen does NOT match the spec, navigate back and re-select.
  * Use the breadcrumb at the top of the page for the "section" field.
"""


async def lookup_labor_time(
    job: JobSpec, vehicle: VehicleFingerprint, max_steps: int = 30
) -> tuple[LaborResult | None, dict]:
    """Returns (labor, meta).  meta["parts"] holds the OEM parts list parsed
    from the same Parts and Labor page."""
    task = _build_task(job, vehicle)
    agent = VisionAgent(portal_url=ALLDATA_HOME, task=task, max_steps=max_steps)

    async with ChromeDebugBrowser() as browser:
        result = await agent.run(browser)

    if not result["extracted"]:
        logger.warning("ALLDATA agent extracted nothing")
        return None, result

    best = max(result["extracted"], key=lambda e: e.get("confidence", 0.0))
    raw = best["data"]
    try:
        if isinstance(raw, str):
            raw = _json.loads(raw)

        section_path = raw.get("section") or ""

        labor = LaborResult(
            operation=str(raw.get("operation", "")),
            hours=float(raw.get("hours", 0.0)),
            source="alldata",
            vehicle_match={
                "reported": raw.get("matched_vehicle"),
                "section": section_path,
                "skill": raw.get("skill"),
            },
            raw_text=str(raw),
            screenshot_path=(
                result["history"][best["step"]].get("screenshot")
                if best["step"] < len(result["history"]) else None
            ),
        )

        # Parts list from the same Parts and Labor page
        parts: list[PartResult] = []
        for p in (raw.get("parts") or []):
            try:
                price = p.get("price")
                price = float(price) if price not in (None, "") else None
                parts.append(PartResult(
                    name=str(p.get("name", "")),
                    oem_number=p.get("oem_number") or None,
                    price=price,
                    vendor="ALLDATA (OEM list)",
                    in_stock=None,
                    source="alldata",
                    screenshot_path=labor.screenshot_path,
                ))
            except Exception as pe:
                logger.warning(f"  skipped malformed part entry {p!r}: {pe}")

    except Exception as e:
        logger.error(f"Failed to parse extracted labor/parts: {e}")
        return None, result

    # Hermes verification (on labor row vs job spec)
    verification = verify_with_hermes(
        extracted={
            "operation": labor.operation,
            "hours": labor.hours,
            "vehicle": labor.vehicle_match,
        },
        job_spec=job.model_dump(),
        vehicle=vehicle.model_dump(),
    )
    logger.info(
        f"Verification: match={verification.match} conf={verification.confidence:.2f} "
        f"reason={verification.reason[:120]}"
    )

    return labor, {
        "agent_run": result,
        "verification": verification.model_dump(),
        "extraction_confidence": best.get("confidence", 0.0),
        "parts": [p.model_dump() for p in parts],
        "section_path": section_path,
    }


if __name__ == "__main__":
    from models.job_spec import JobSpec, VehicleFingerprint

    sample_job = JobSpec(
        system="braking",
        subsystem="front_brakes",
        symptom="grinding noise on braking",
        severity="medium",
        keywords=["brake pad", "front brake", "rotor"],
    )
    sample_vehicle = VehicleFingerprint(
        vin="2HGFC2F59JH123456",
        year=2018, make="Honda", model="Civic", trim="LX", engine="2.0L",
    )
    labor, meta = asyncio.run(lookup_labor_time(sample_job, sample_vehicle))
    print("\n=== LABOR ===")
    if labor:
        print(labor.model_dump_json(indent=2))
    print("\n=== PARTS ===")
    print(_json.dumps(meta.get("parts", []), indent=2))
    print("\n=== VERIFICATION ===")
    print(meta.get("verification"))
