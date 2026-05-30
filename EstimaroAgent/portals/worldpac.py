"""Worldpac SpeedDial vendor agent — hybrid Playwright prep + extract-only agent.

Worldpac's catalog uses Material-UI hidden checkboxes (`input[type=checkbox]`
class `jss19`, no id/name) wrapped in visible-but-non-input DIVs. The vision
agent's overlay landed on the wrapper, so its click never toggled the real
input — every estimate ended in a 180s timeout loop between catalog and the
pricing page. We now drive the checkbox + PRICE button deterministically via
stable Playwright selectors and hand off to the agent only for extraction.

Stable selectors (verified 2026-05-30):
  * Part-type row:  .sd-part-node:has(.sd-part-node-desc-text:text-is('<label>'))
  * Hidden checkbox inside that row:  input[type=checkbox]
  * PRICE button:                     #price-button
  * Catalog tab:                      hash route #/catalog
  * Pricing results:                  hash route #/pna
"""
import asyncio
import re
from typing import Optional, Tuple

from loguru import logger

from core.browser import ChromeDebugBrowser
from models.job_spec import VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "Worldpac"
PORTAL_URL = "https://speeddial.worldpac.com/#/"
CATALOG_URL = "https://speeddial.worldpac.com/#/catalog"

# Customer-complaint vocabulary → the canonical part-type label Worldpac's
# catalog lists in its right-side "Part Type" panel. Keys are matched
# loosely (substring, case-insensitive) so "Front Pads", "Brake Pad Set
# (Front)", "brake pads" all reach the same Worldpac row.
_LABEL_MAP = [
    (r"brake\s*pad", "Brake Pad Set"),
    (r"\bpads?\b", "Brake Pad Set"),
    (r"brake\s*(disc|rotor)", "Brake Disc"),
    (r"\brotors?\b", "Brake Disc"),
    (r"brake\s*caliper", "Brake Caliper"),
    (r"\bcalipers?\b", "Brake Caliper"),
    (r"oil\s*filter", "Oil Filter"),
    (r"air\s*filter", "Air Filter"),
    (r"cabin\s*filter|cabin\s*air", "Cabin Air Filter"),
    (r"spark\s*plug", "Spark Plug"),
    (r"control\s*arm", "Control Arm"),
    (r"shock", "Shock Absorber"),
    (r"strut", "Strut Assembly"),
    (r"wheel\s*bearing", "Wheel Bearing"),
]


def _worldpac_label(part_type: str) -> Optional[str]:
    """Map a free-text part request to Worldpac's catalog label."""
    if not part_type:
        return None
    t = part_type.lower()
    for pattern, label in _LABEL_MAP:
        if re.search(pattern, t):
            return label
    return None


def _build_task(vehicle, part_type: str, label: str, oem_hint: Optional[str]) -> str:
    hint = f'\n  OEM number hint (for matching only): {oem_hint}' if oem_hint else ""
    return f"""
You are inside the Worldpac SpeedDial pricing-results page. The vehicle is set,
the {label!r} category is checked, and the PRICE button has already been
clicked — the page in front of you IS the priced grid of brake-pad-set rows
for the customer's vehicle.

YOUR ONLY JOB: read the visible result rows and emit the extraction JSON.{hint}

VEHICLE:   {vehicle.year} {vehicle.make} {vehicle.model}
PART TYPE: {label} (customer asked for {part_type!r})

WHAT TO READ:
  The grid lists one row per brand/sku option. For each row capture: BRAND
  (e.g. "Akebono EURO", "ATE", "Bosch", "Genuine"), PART NUMBER, DESCRIPTION,
  PRICE (your-price / buy-price column), AVAILABILITY / STOCK (e.g. "Today",
  "Monday — In Network", "Extended Network"), and POSITION if the row labels
  one (Front / Rear). Capture up to 6 of the cheapest in-stock rows; ignore
  Rear-position rows if {part_type!r} clearly asks for Front, and vice versa.

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
  * Report only rows actually visible — never invent a price.
  * price = numeric your-price / buy-price if shown, else null.
  * in_stock = true if availability says Today / In Network / a quantity,
    false if Out of Stock / Special Order, null if unclear.
  * Only use action="ask_human" if no priced rows are present at all
    (e.g. the page is still loading after 10 seconds).
"""


async def _prep_search(vehicle, part_type: str) -> tuple[Optional[str], Optional[str]]:
    """Open the catalog, tick the matching part-type row, click PRICE.

    Returns (error, label). `error` is None on success; `label` is the
    Worldpac category label (used by the extraction prompt).
    """
    label = _worldpac_label(part_type)
    if not label:
        return f"unmapped_part_type :: no Worldpac label for {part_type!r}", None

    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus(CATALOG_URL, url_match="worldpac.com")
            # Land on a clean catalog state even if a previous run left the
            # tab on /pna or a different category.
            if "/catalog" not in page.url:
                await page.goto(CATALOG_URL, wait_until="domcontentloaded")
                await asyncio.sleep(2)

            row_sel = (
                f".sd-part-node:has(.sd-part-node-desc-text:text-is({label!r}))"
            )
            row = page.locator(row_sel).first
            try:
                await row.scroll_into_view_if_needed(timeout=10_000)
            except Exception:
                # The row only appears after a vehicle is set AND the relevant
                # catalog category (e.g. "Brake Disc" group) is expanded. We
                # don't try to drive the vehicle picker here — Worldpac
                # persists the last vehicle in the session, so a recent
                # successful job leaves us pre-set; if not, fail cleanly.
                return (
                    f"row_not_found :: {label!r} not visible in the catalog — "
                    f"vehicle may not be set for {vehicle.year} {vehicle.make}",
                    label,
                )

            cb = row.locator("input[type=checkbox]")
            # force=True because the MUI checkbox is visually hidden behind
            # its styled wrapper; Playwright's normal visibility guard would
            # refuse otherwise. The native check() still routes through the
            # input's onChange handler, so React picks up the state update.
            await cb.check(timeout=5_000, force=True)
            await asyncio.sleep(0.5)

            # Verify the toggle actually took. Some MUI builds need a second
            # nudge if React hasn't flushed when we read the state.
            if not await cb.is_checked(timeout=2_000):
                await cb.check(timeout=3_000, force=True)
                await asyncio.sleep(0.5)

            try:
                await page.click("#price-button", timeout=8_000)
            except Exception as e:
                return f"price_button_failed :: {type(e).__name__}: {str(e)[:120]}", label
            # Worldpac navigates to /pna and fetches the priced grid; allow it
            # a generous moment because the underlying request can be slow.
            for _ in range(8):
                await asyncio.sleep(1.0)
                if "/pna" in page.url:
                    break
            if "/pna" not in page.url:
                return f"price_navigation_failed :: still at {page.url}", label
            # Let the grid populate before the agent screenshots it.
            await asyncio.sleep(3)
    except Exception as e:
        logger.error(f"[{PORTAL_NAME}] _prep_search failed: {type(e).__name__}: {e}")
        return f"prep_failed :: {type(e).__name__}: {str(e)[:160]}", label
    return None, label


async def lookup(
    vehicle,
    part_type: str,
    *,
    oem_hint: Optional[str] = None,
    max_steps: int = 10,
    timeout: int = 120,
) -> Tuple[list[VendorQuote], dict]:
    """Set up the priced grid deterministically, then extract via the agent."""
    from portals.auth import ensure_logged_in
    status = await ensure_logged_in("worldpac")
    if not status.get("ok"):
        return [], {"error": f"login_failed :: {status.get('error') or status.get('action')}",
                    "history": [], "steps_taken": 0, "login_status": status}

    prep_err, label = await _prep_search(vehicle, part_type)
    if prep_err:
        return [], {"error": prep_err, "history": [], "steps_taken": 0}

    task = _build_task(vehicle, part_type, label, oem_hint)
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal=None)
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

    logger.info(f"[{PORTAL_NAME}] {part_type!r} ({label}) -> {len(quotes)} result row(s)")
    return quotes, meta


if __name__ == "__main__":
    from models.job_spec import VehicleFingerprint
    veh = VehicleFingerprint(vin="WDDPK4HA3FF102840", year=2015,
                             make="Mercedes-Benz", model="SLK-Class")
    quotes, meta = asyncio.run(lookup(veh, "Front Pads", oem_hint="0074209220"))
    print("\n=== QUOTES ===")
    for x in quotes:
        print(x.model_dump_json(indent=2))
    print("\n=== META (no history) ===")
    print({k: v for k, v in meta.items() if k != "history"})
