"""SSF (Eurolink) vendor agent.

SSF Auto Parts is a European-parts distributor. Its shop has a "Search Part
Number" box that takes an OEM/part number and returns matching parts with the
shop's price and availability — one of the real price+stock sources for the
estimate. (A "Find by VIN" path also exists for catalogue browsing.)
"""
from typing import Optional, Tuple

from loguru import logger

from models.job_spec import VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "SSF"
PORTAL_URL = "https://shop.ssfautoparts.com/Catalog"


def _build_task(vehicle, part_type: str, oem_hint: Optional[str]) -> str:
    hint = f'\n  OEM number hint (for matching only): {oem_hint}' if oem_hint else ""
    return f"""
You are inside the SSF (Eurolink) parts shop. The shop is already logged in.

SSF is an AFTERMARKET distributor — set the VEHICLE first (it has a "Find by VIN"
box), then browse the part category. Genuine OEM numbers are NOT reliable search
keys here.

VEHICLE:   {vehicle.year} {vehicle.make} {vehicle.model}
  VIN:     {vehicle.vin}
FIND PARTS: {part_type}{hint}

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. Set the vehicle. Easiest: open the "Recent Vehicles" / "Quick Vehicle"
     dropdown and pick the entry for VIN {vehicle.vin} ({vehicle.year}
     {vehicle.make} {vehicle.model}). Otherwise type the VIN into the
     "Find by VIN #" box AND click the submit/magnifier button right next to it.
  2. WAIT for the page to change from the home/sponsor page to the vehicle's
     parts catalogue (it will show parts categories or an assembly tree). If you
     are still on the home page, the VIN was not submitted — submit it again.
  3. In the catalogue, go to the brakes group, then the brake-pad category. If a
     category like "Brakes" or "Brake Pads" is not visible, use action="find"
     with that text to bring it into view, then click it.
  4. On the parts list, read each option: BRAND / LINE, PART NUMBER, DESCRIPTION,
     PRICE, and AVAILABILITY / stock (e.g. "In Stock", a quantity, a branch/ETA).

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "vehicle": "<vehicle text shown>",
    "part_type": "{part_type}",
    "results": [
      {{
        "brand": "<brand / line>",
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
  * Report only rows actually visible in the results — never invent prices.
  * price = numeric your/buy price if shown, else null.
  * in_stock = true if availability clearly indicates stock on hand, false if out
    of stock / special order, null if unclear.
  * Capture up to the first 6 result rows.
  * Only use action="ask_human" if you cannot resolve the vehicle or reach the
    part category after genuinely trying.
"""


async def lookup(
    vehicle,
    part_type: str,
    *,
    oem_hint: Optional[str] = None,
    max_steps: int = 22,
    timeout: int = 300,
) -> Tuple[list[VendorQuote], dict]:
    """Browse SSF by vehicle (Find by VIN) + part type. Returns (quotes, meta)."""
    task = _build_task(vehicle, part_type, oem_hint)
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal="ssf")
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
