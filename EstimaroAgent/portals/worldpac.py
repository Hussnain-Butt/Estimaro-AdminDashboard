"""Worldpac SpeedDial vendor agent.

Worldpac is an aftermarket/OE distributor. Its SpeedDial search box accepts a
free-text query — an OEM/part number, or "Year Make Model + part type" — and
returns brand options with buy price and warehouse availability. This is one of
the real price+stock sources for the estimate.
"""
from typing import Optional, Tuple

from loguru import logger

from models.job_spec import VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "Worldpac"
PORTAL_URL = "https://speeddial.worldpac.com/#/"


def _build_task(vehicle, part_type: str, oem_hint: Optional[str]) -> str:
    hint = f'\n  OEM number hint (for matching only): {oem_hint}' if oem_hint else ""
    return f"""
You are inside the Worldpac SpeedDial catalogue. The shop is already logged in.

Worldpac is an AFTERMARKET distributor — it is searched by VEHICLE + part type,
NOT by genuine OEM number. Set the vehicle first, then browse the part category.

VEHICLE:   {vehicle.year} {vehicle.make} {vehicle.model}
  VIN:     {vehicle.vin}
FIND PARTS: {part_type}{hint}

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. Look at the TOP of the page. If it does NOT already show "{vehicle.year}
     {vehicle.make} {vehicle.model}", click "Select Vehicle", type the VIN
     {vehicle.vin} into the VIN field, and apply it.
  2. VERY IMPORTANT: once the vehicle is shown at the top, DO NOT open the
     "Select Vehicle" / vehicle box again. Do not retype the VIN. Move on.
  3. Open the "Catalog" tab. In the left-hand catalog tree, expand "Parts" and
     click the "Brake" category.
  4. The "Selected Part Types" list on the right has CHECKBOXES (it may show
     "X of 50 Parts Selected"). FIRST uncheck anything already selected that is
     not what you want (e.g. uncheck "Brake Caliper"). Then CHECK ONLY the entry
     for this job — for brake pads check "Brake Pad Set" (or "Brake Pad" / "Disc
     Brake Pad"). Make sure ONLY that one is checked.
  5. Now click the "PRICE" button. The priced grid then shows ONLY that part
     type's options. Read each row: BRAND, PART NUMBER, DESCRIPTION, PRICE, and
     AVAILABILITY / stock. Extract those. If the grid shows a different part type
     than you wanted, go Back to Catalog and fix the checkbox selection.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "vehicle": "<vehicle text shown>",
    "part_type": "{part_type}",
    "results": [
      {{
        "brand": "<brand>",
        "part_number": "<part number>",
        "description": "<row description>",
        "price": <number or null>,
        "availability": "<raw stock text>",
        "in_stock": <true|false|null>
      }}
    ]
  }}
Then action="done".

CRITICAL RULES:
  * Report only rows actually visible in the results grid — never invent prices.
  * price is the numeric buy/your-price if shown, else null.
  * in_stock = true if availability clearly indicates stock on hand, false if it
    says out of stock / special order, null if unclear.
  * Capture up to the first 6 most relevant result rows.
  * Only use action="ask_human" if you cannot set the vehicle or reach any parts
    grid after genuinely trying both VIN and Year/Make/Model.
"""


async def lookup(
    vehicle,
    part_type: str,
    *,
    oem_hint: Optional[str] = None,
    max_steps: int = 22,
    timeout: int = 300,
) -> Tuple[list[VendorQuote], dict]:
    """Browse Worldpac by vehicle + part type. Returns (quotes, meta) — one
    VendorQuote per aftermarket option found."""
    task = _build_task(vehicle, part_type, oem_hint)
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal="worldpac")
    if raw is None:
        return [], meta

    screenshot = None
    try:
        hist = meta.get("history") or []
        bs = meta.get("best_step")
        if bs is not None and bs < len(hist):
            screenshot = hist[bs].get("screenshot")
    except Exception:
        pass

    quotes: list[VendorQuote] = []
    for r in (raw.get("results") or []):
        try:
            price = r.get("price")
            price = float(price) if price not in (None, "", "null") else None
        except (TypeError, ValueError):
            price = None
        in_stock = r.get("in_stock")
        if isinstance(in_stock, str):
            in_stock = in_stock.strip().lower() in ("true", "yes", "in stock", "instock")
        quotes.append(VendorQuote(
            vendor=PORTAL_NAME,
            requested_part=str(oem_hint or part_type),
            matched_part_name=r.get("description"),
            oem_number=r.get("part_number") or None,
            brand=r.get("brand") or None,
            price=price,
            list_price=None,
            in_stock=in_stock if isinstance(in_stock, bool) else None,
            availability=r.get("availability"),
            found=True,
            note=None,
            screenshot_path=screenshot,
        ))

    logger.info(f"[{PORTAL_NAME}] {part_type!r} -> {len(quotes)} result row(s)")
    return quotes, meta


if __name__ == "__main__":
    import asyncio
    from models.job_spec import VehicleFingerprint
    veh = VehicleFingerprint(vin="W1KAF4GB3PR122770", year=2023,
                             make="Mercedes-Benz", model="C-Class")
    quotes, meta = asyncio.run(lookup(veh, "front brake pads", oem_hint="0004211202"))
    print("\n=== QUOTES ===")
    for x in quotes:
        print(x.model_dump_json(indent=2))
    print("\n=== META (no history) ===")
    print({k: v for k, v in meta.items() if k != "history"})
