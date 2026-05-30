"""PartsLink24 OEM parts-catalog agent.

PartsLink24 is the genuine-OEM EPC for European brands (Audi, BMW, Mercedes,
VW, MINI, Bentley, Jaguar/Land Rover, ...). Given a VIN it resolves the exact
vehicle and lets us navigate the parts catalogue to read OEM part numbers and
list prices.

Role in the pipeline: confirm/enrich the OEM part numbers ALLDATA produced and
attach the OEM list price, returned as uniform VendorQuote rows.

Subscription tiers: the "Direct entry" VIN-search field is gated on a paid
subscription. On a Demo account the input is rendered with `Mui-disabled`,
which causes Playwright `click()` to time out — the agent then loops retrying
the same broken action. We detect the disabled state up-front, skip the agent
run with a clean `demo_subscription` error, and on paid accounts deterministic
VIN entry lets the agent jump straight to the parts page.
"""
import asyncio
from typing import Optional, Tuple

from loguru import logger

from core.browser import ChromeDebugBrowser
from models.job_spec import JobSpec, VehicleFingerprint, VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "PartsLink24"
PORTAL_URL = "https://www.partslink24.com/partslink24/user/brandMenu.do"

# Material-UI generates auto-ids like ":r2:" for the Direct-entry input; that
# value is not stable across page reloads. We locate it by placeholder text.
SEL_DIRECT_ENTRY = "input[placeholder='Direct entry']"

# European marques PartsLink24 actually covers. Used to skip the portal fast
# for vehicles it can never serve (domestic/Asian) instead of wasting a run.
SUPPORTED_MAKES = {
    "audi", "bentley", "bmw", "mini", "jaguar", "land rover", "landrover",
    "mercedes", "mercedes-benz", "volkswagen", "vw", "man", "porsche", "seat", "skoda",
}

# Mapping from the user-facing make to the brand-app URL slug PartsLink24 uses.
BRAND_APP_SLUG = {
    "mercedes": "mercedes_parts",
    "mercedes-benz": "mercedes_parts",
    "bmw": "bmw_parts",
    "mini": "mini_parts",
    "audi": "audi_parts",
    "volkswagen": "vw_parts",
    "vw": "vw_parts",
    "porsche": "porsche_parts",
    "jaguar": "jlr_parts",
    "land rover": "jlr_parts",
    "landrover": "jlr_parts",
    "bentley": "bentley_parts",
    "seat": "seat_parts",
    "skoda": "skoda_parts",
    "man": "man_parts",
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

NAVIGATION PLAN:
  IF THE VEHICLE IS ALREADY RESOLVED (you can see an assembly-group tree or
  parts illustration for this VIN), skip directly to step 4.

  1. On the brand catalogue, look at the "Direct entry" box at the top left.
     - If it is ENABLED, type the VIN and press the magnifier — the catalogue
       resolves the exact vehicle in one step.
     - If it is DISABLED / greyed out (a "Demo" watermark across the page is a
       sure sign), DO NOT keep clicking it — that field is locked on demo
       subscriptions. Fall through to step 2.
  2. Demo / manual path: drill the model picker columns shown on the page.
     a. In the leftmost "Scope" column, click "PC" (passenger car).
     b. The "Series" column populates. Click the series matching the vehicle —
        for {vehicle.make} {vehicle.model} ({vehicle.year}), pick the series
        whose name contains the model family (e.g. "C-Class" for a C300).
        Use action="find" if the series text is not visible.
     c. The "Model" column populates. Click the model whose year range covers
        {vehicle.year} and whose engine/sales-type matches the VIN's variant.
     d. The catalogue stores the resolved vehicle and shows it in the breadcrumb
        at the top (e.g. "Start > Mercedes-Benz > C206046 C 300 Sedan").
        At this point the vehicle is selected — do not keep clicking the same
        model row, and do not click the "Start" breadcrumb (it goes back to
        the brand list and loses the selection).
  3. From the resolved-vehicle state, open the assembly-group tree. The tree
     opens from the left sidebar icons (a car icon / assembly-group icon at
     the very left edge of the page). Click that icon — NOT "Start", NOT the
     brand name in the breadcrumb. If the first click "had no effect", try the
     next icon down rather than re-clicking the same one.
  4. Open the assembly-group tree and navigate to the subsystem matching the
     symptom:
       - brakes / pads / rotors -> Brake system -> Front (or Rear) brake / Disc brake
       - oil / lubrication      -> Engine -> Lubrication / Oil filter
       - suspension / steering  -> Front axle / Suspension
       - ignition / spark plug  -> Engine -> Ignition
  5. On the parts illustration / list page you will see rows with a PART NUMBER,
     a DESCRIPTION and (where shown) a PRICE. Match them to the wanted parts.
     Demo subscriptions hide prices — emit the part numbers anyway with
     price=null.

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
  * NEVER click the same disabled "Direct entry" field twice. If your first
    click times out OR you see a "Demo" watermark, the field is locked: use the
    model-picker path (step 2) instead.
  * Only use action="ask_human" if you truly cannot reach a parts page via
    EITHER the Direct entry path OR the model-picker tree.
"""


async def _prep_vehicle(vehicle: VehicleFingerprint) -> tuple[Optional[str], dict]:
    """Open the brand catalogue and (when possible) resolve the vehicle via VIN.

    Returns ``(error, info)``:
      * ``error=None`` on success — info["direct_entry"] is True if we filled
        the VIN deterministically, False if the field is locked (demo tier)
        and the agent must drill the model picker.
      * ``error="..."`` on hard failures (no brand slug for this make,
        Chrome reachability, etc.).
    """
    make_key = (vehicle.make or "").strip().lower()
    slug = BRAND_APP_SLUG.get(make_key)
    if not slug:
        return f"no_brand_app :: {vehicle.make!r} has no PartsLink24 brand-app slug", {}

    brand_app_url = f"https://www.partslink24.com/pl24-app/{slug}/0/0?desktop=true&lang=en"
    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus(brand_app_url, url_match="partslink24.com")
            # If a stale tab opened earlier on a different brand, force-navigate.
            if slug not in page.url:
                await page.goto(brand_app_url, wait_until="domcontentloaded")
            await page.wait_for_selector(SEL_DIRECT_ENTRY, timeout=15_000)
            await asyncio.sleep(2)  # let Material-UI finish hydrating
            disabled = await page.evaluate(
                f"""() => {{
  const el = document.querySelector("{SEL_DIRECT_ENTRY}");
  if (!el) return null;
  return el.disabled || (el.className || '').toString().includes('Mui-disabled');
}}"""
            )
            if disabled is None:
                return "direct_entry_missing :: brand app rendered but no Direct entry field found", {}
            if disabled:
                logger.info(f"[{PORTAL_NAME}] Direct entry is disabled (demo tier) — "
                            f"agent will use the model-picker tree")
                return None, {"direct_entry": False, "demo": True}

            await page.fill(SEL_DIRECT_ENTRY, vehicle.vin)
            await page.press(SEL_DIRECT_ENTRY, "Enter")
            await asyncio.sleep(5)  # vehicle resolution + redirect
            return None, {"direct_entry": True, "demo": False}
    except Exception as e:
        logger.error(f"[{PORTAL_NAME}] _prep_vehicle failed: {type(e).__name__}: {e}")
        return f"prep_failed :: {type(e).__name__}: {str(e)[:160]}", {}


async def lookup(
    vehicle: VehicleFingerprint,
    part_type: Optional[str] = None,
    *,
    oem_hint: Optional[str] = None,
    timeout: int = 300,
    max_steps: int = 25,
    job: Optional[JobSpec] = None,
    target_parts: Optional[list[dict]] = None,
) -> Tuple[list[VendorQuote], dict]:
    """Vendor-pipeline compatible entry — same shape as worldpac/ssf.lookup().

    `vendors.gather_quotes` calls this with `(vehicle, part_type, oem_hint=...,
    timeout=...)`. The PL24 prompt was originally written around a `JobSpec`
    + target-parts list, so when those aren't supplied we synthesise a minimal
    JobSpec from `part_type` and a single-row target_parts list keyed by
    `oem_hint`. Standalone callers can still pass `job` + `target_parts`
    explicitly via kwargs.
    """
    if job is None:
        job = JobSpec(
            system="other",
            subsystem=part_type or "",
            symptom=part_type or "",
            severity="medium",
            keywords=[part_type] if part_type else [],
        )
    if target_parts is None:
        target_parts = [{"name": part_type or "Part", "oem_number": oem_hint}]
    return await _lookup_impl(job, vehicle, target_parts,
                              max_steps=max_steps, timeout=timeout)


async def _lookup_impl(
    job: JobSpec,
    vehicle: VehicleFingerprint,
    target_parts: list[dict],
    *,
    max_steps: int = 25,
    timeout: int = 300,
) -> Tuple[list[VendorQuote], dict]:
    """Underlying agent run. Use `lookup()` for the canonical vendor-pipeline
    entry; this signature is kept so the standalone __main__ smoke test (and
    any future job-aware caller) can pass a full JobSpec + target list."""
    if not supports(vehicle):
        return [], {"skipped": f"{vehicle.make} not covered by PartsLink24"}

    # Login + brand-app navigation + VIN entry are deterministic steps; the
    # agent should only need to navigate the assembly tree + extract.
    from portals.auth import ensure_logged_in
    status = await ensure_logged_in("partslink24")
    if not status.get("ok"):
        return [], {"error": f"login_failed :: {status.get('error') or status.get('action')}",
                    "history": [], "steps_taken": 0, "login_status": status}

    prep_err, prep_info = await _prep_vehicle(vehicle)
    if prep_err:
        return [], {"error": prep_err, "history": [], "steps_taken": 0}
    if not prep_info.get("direct_entry"):
        # Demo tier — VIN field locked. The agent prompt teaches the model-tree
        # fallback, but warn the operator so they know prices won't come back.
        logger.warning(f"[{PORTAL_NAME}] running on demo subscription (no prices)")

    task = _build_task(job, vehicle, target_parts)
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal=None)
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
    quotes, meta = asyncio.run(
        lookup(sample_vehicle, job=sample_job, target_parts=target)
    )
    print("\n=== QUOTES ===")
    for q in quotes:
        print(q.model_dump_json(indent=2))
    print("\n=== META ===")
    print({k: v for k, v in meta.items() if k != "history"})
