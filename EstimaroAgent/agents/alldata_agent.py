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
     The vehicle banner at the top of every subsequent page shows the
     year/make/model and ends with the VIN. If that VIN does NOT contain
     the last 6 chars of the target VIN above, you picked the wrong vehicle:
     use action="ask_human" with reason="vehicle_mismatch" rather than continuing.
  3. NAVIGATE THE CATEGORY TREE — FILTER-FIRST STRATEGY.

     Every category and sub-category page in ALLDATA has a filter input near
     the top, labelled "Type term and hit enter to filter list below". This
     filter is your PRIMARY navigation tool — it is deterministic, instant,
     and works across every vehicle make. Card-trees differ per make
     (a "Lubrication System" card that exists for Honda does NOT exist on
     Volvo's parent page), so do NOT memorise tree paths. Filter instead.

     Algorithm:
       a. After picking the vehicle you land on a page of parent-category
          cards (e.g. "Engine, Cooling and Exhaust", "Brakes and Traction
          Control", "Transmission and Drivetrain", ...). Identify the ONE
          parent that most plausibly contains the symptom and click it.
       b. On the resulting page you see component cards AND a filter input.
          Use action="type" on the filter input with value = the most
          specific job keyword from the table below. Press Enter is NOT
          required — typing fires the filter live.
       c. The card list will reduce to cards whose name contains the keyword.
          Click the matching card.
       d. If filter yields ZERO cards, the keyword is too specific for this
          make's catalogue. Clear the filter (action="type" with value="") and
          retry with a BROADER keyword from the fallback column. If that also
          yields nothing, click the breadcrumb to go back ONE level and try a
          DIFFERENT parent category.

     Job → filter keyword table (try primary first, then fallback):

       Brake (front pads / grinding):   primary "pad"      fallback "brake"
       Brake (rear pads):               primary "pad"      fallback "brake"
       Brake (rotor / disc):            primary "rotor"    fallback "disc"
       Oil change / oil filter:         primary "oil"      fallback "lubricat"
       Coolant / radiator / thermostat: primary "cool"     fallback "radiator"
       Transmission fluid / shift:      primary "transmis" fallback "drivetrain"
       Spark plug / ignition:           primary "spark"    fallback "ignition"
       Belt / serpentine / tensioner:   primary "belt"     fallback "drive"
       Battery:                         primary "battery"  fallback "charging"
       Alternator:                      primary "alternat" fallback "charging"
       Starter:                         primary "starter"  fallback "starting"
       Exhaust / muffler / catalytic:   primary "exhaust"  fallback "muffler"
       Suspension / strut / shock:      primary "strut"    fallback "suspens"
       Control arm / ball joint:        primary "control"  fallback "suspens"
       Wheel bearing:                   primary "bearing"  fallback "wheel"

     If the symptom isn't in this table, pick the parent category most likely
     to contain it, then filter by the most-distinctive noun from the job's
     Keywords field above.

     HARD RULES for navigation:
       * Never run action="find" or action="scroll" more than TWICE on the
         same page. If the second attempt fails, the item is not on this page
         — use the filter, breadcrumb back, or ask_human.
       * If you clicked a wrong parent and the page no longer shows the
         category cards you need, click the breadcrumb (typically "Vehicle"
         or the parent name in the top-left of the content area) to go back
         one level. Do NOT navigate by URL.
       * Do not click "Engine" as a catch-all — on most makes, oil/cooling/
         exhaust items live OUTSIDE "Engine" as sibling cards. Filter first
         on the parent page; only enter "Engine" if filter narrows to a card
         inside it.

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

    # Vehicle-match hard guard. ALLDATA prints the picked vehicle's VIN in the
    # banner on every Parts-and-Labor page, so the suffix of the target VIN
    # MUST appear in the extraction-time page text. If it doesn't, the agent
    # picked the wrong vehicle (e.g. a stale "Recent Vehicles" row from a
    # previous customer) and the labor row is for a different car entirely.
    # That's a silent-wrong-estimate failure mode — never let it through to
    # the estimate. We use a 6-char suffix because the full 17-char VIN is
    # sometimes broken across spans (`VIN 58 ` + `B5244T3 ` + `YV1SZ...`) and
    # the tail is the most-unique, contiguous slice.
    page_text_raw = (best.get("page_text") or "")
    page_text_lc = page_text_raw.lower()
    target_vin = (vehicle.vin or "").strip().upper()
    if target_vin and len(target_vin) >= 6 and page_text_lc:
        vin_suffix = target_vin[-6:].lower()
        # Strip whitespace from page text for the suffix check so VINs broken
        # across HTML spans (" 78311 " vs "78311") still match.
        page_text_compact = "".join(page_text_lc.split())
        if vin_suffix not in page_text_lc and vin_suffix not in page_text_compact:
            logger.error(
                f"Vehicle-match guard FAIL: target VIN suffix {vin_suffix!r} "
                f"not present in extraction page — agent operated on wrong vehicle"
            )
            return None, {
                **result,
                "fail_reason": "vehicle_mismatch_on_extract_page",
                "target_vin_suffix": vin_suffix,
                "extraction_confidence": 0.0,
            }

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
