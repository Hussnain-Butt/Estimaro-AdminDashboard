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
     ALLDATA's tree is two levels deep: a parent category (a header like
     "Engine, Cooling and Exhaust") expands into several sibling cards
     ("Engine", "Cooling System", "Exhaust System", "Lubrication System",
     etc.). The subsystem you want is a DIRECT SIBLING of the obvious
     "Engine" card, NOT a child of it — do NOT click "Engine" first if the
     subsystem you actually want (e.g. Lubrication System) is already visible
     as its own card on the same screen.
     - For brakes:    Brakes and Traction Control -> Disc Brake System -> Brake Pad (front pads complaint)
                                                                       -> Brake Rotor (rotor complaint)
     - For engine oil / oil change / oil filter:
                       Engine, Cooling and Exhaust -> Lubrication System (sibling, NOT inside "Engine")
                       (fallback: if Lubrication System isn't visible after expanding the parent,
                        try "Engine" -> "Oil and Filter" or "Lubrication" inside it; if still
                        nothing, use action="find" with value="Lubrication System" or "Oil Filter".)
     - For transmission fluid / shift / clutch:
                       Transmission and Drivetrain -> Automatic Transmission (auto) or Manual Transmission
     - For suspension/shocks/struts/control arm:
                       Suspension and Steering -> the specific component (Shock, Strut, Control Arm)
     - For ignition / spark plug / coil:
                       Engine, Cooling and Exhaust -> Engine -> Ignition System -> Spark Plug
     - For battery / starter / alternator:
                       Starting and Charging -> the specific component
     - For cooling / coolant / radiator / thermostat:
                       Engine, Cooling and Exhaust -> Cooling System (sibling, NOT inside "Engine")
     - For belts / pulleys / tensioner:
                       Engine, Cooling and Exhaust -> Belt Driven Accessories (or Drive Belts)
     - For exhaust / muffler / catalytic converter:
                       Engine, Cooling and Exhaust -> Exhaust System
     If you clicked a wrong card and the expected sibling card is no longer
     visible (the tree drilled one level too deep), use the breadcrumb at the
     top of the page to navigate BACK one level — do NOT keep retrying find /
     scroll on the wrong page. Returning to the parent and re-picking is far
     cheaper than 4 failed find attempts.
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
    agent = VisionAgent(portal_url=ALLDATA_HOME, task=task, max_steps=max_steps,
                        login_portal="alldata")

    async with ChromeDebugBrowser() as browser:
        result = await agent.run(browser)

    if not result["extracted"]:
        logger.warning("ALLDATA agent extracted nothing")
        return None, result

    best = max(result["extracted"], key=lambda e: e.get("confidence", 0.0))
    raw = best["data"]
    # Screenshot-vs-claim sanity check (cheap DOM grep). The model occasionally
    # hallucinates an operation/hours combo that doesn't actually appear on
    # the rendered page. We don't reject outright — vision is still our best
    # signal — but we downgrade confidence so the verification + gating layers
    # later in the pipeline see it as uncertain.
    grounded_in_page = True
    try:
        page_text = (best.get("page_text") or "").lower()
        if page_text:
            preview = raw
            if isinstance(preview, str):
                try:
                    preview = _json.loads(preview)
                except Exception:
                    preview = {}
            claimed_op = str((preview or {}).get("operation") or "").strip().lower()
            claimed_hours = (preview or {}).get("hours")
            if claimed_op:
                # Cheap substring check; ALLDATA's labor row text usually
                # appears verbatim in the table. Word-by-word fallback handles
                # minor reorderings like "Front Pads" vs "Pads, Front".
                if claimed_op in page_text:
                    pass
                else:
                    op_words = [w for w in claimed_op.split() if len(w) > 2]
                    hits = sum(1 for w in op_words if w in page_text)
                    if op_words and hits / len(op_words) < 0.7:
                        grounded_in_page = False
                        logger.warning(
                            f"DOM-grep: claimed operation {claimed_op!r} not "
                            f"grounded in page text (hits {hits}/{len(op_words)}) "
                            f"— downgrading confidence")
            if claimed_hours is not None:
                # Hours like "1.2" should appear somewhere in the page.
                hours_str = str(claimed_hours)
                if hours_str not in page_text:
                    grounded_in_page = False
                    logger.warning(
                        f"DOM-grep: claimed hours {hours_str!r} not in page text "
                        f"— downgrading confidence")
    except Exception as e:
        logger.warning(f"DOM-grep verify error (non-fatal): {e}")
    if not grounded_in_page:
        # Cap to 0.6 so downstream gating cannot auto-finalize this.
        best["confidence"] = min(float(best.get("confidence", 0.0)), 0.6)
        best["grounded_in_page"] = False
    else:
        best["grounded_in_page"] = True
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
