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


def _build_task(search_query: str, expected_part: Optional[str]) -> str:
    expect = f'\n  Expected part (for matching): {expected_part}' if expected_part else ""
    return f"""
You are inside the Worldpac SpeedDial catalogue. The shop is already logged in.

SEARCH FOR: "{search_query}"{expect}

The main search box (placeholder "Year, Make, Model / Part Type / Part Number")
accepts either an OEM/part number OR a "year make model + part type" phrase.

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. Click the main search box, type EXACTLY: {search_query}
  2. Press Enter (or click the search icon) to run the search.
  3. Wait for the results grid to load. Each result row typically shows a BRAND,
     a PART NUMBER, a DESCRIPTION, a PRICE, and an AVAILABILITY / stock column
     (e.g. "In Stock", a quantity, or a warehouse/ETA).
  4. IMPORTANT — Worldpac's free-text search works for a PART NUMBER but NOT for a
     "year make model + part type" phrase (that returns "No products were found").
     If you searched a vehicle+part-type phrase and see "No products were found":
       a. Click the "Select Vehicle" button (top-left of the search bar).
       b. Enter / pick the Year, Make and Model.
       c. Then search the PART TYPE (e.g. "brake pad") or open Catalog and browse
          to the part category to reach the priced results grid.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "search_term": "{search_query}",
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
  * Capture up to the first 6 result rows (the most relevant brands).
  * If the search returns nothing, confidence < 0.6 and action="ask_human" with
    the exact message Worldpac showed.
"""


async def lookup(
    search_query: str,
    *,
    expected_part: Optional[str] = None,
    max_steps: int = 18,
    timeout: int = 240,
) -> Tuple[list[VendorQuote], dict]:
    """Search Worldpac by `search_query` (OEM number or 'YMM + part type').
    Returns (quotes, meta) — one VendorQuote per result row."""
    task = _build_task(search_query, expected_part)
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
            requested_part=str(expected_part or search_query),
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

    logger.info(f"[{PORTAL_NAME}] '{search_query}' -> {len(quotes)} result row(s)")
    return quotes, meta


if __name__ == "__main__":
    import asyncio
    # On the VPS, run against the logged-in session with a realistic query.
    q = "2015 Mercedes-Benz C300 front brake pads"
    quotes, meta = asyncio.run(lookup(q))
    print("\n=== QUOTES ===")
    for x in quotes:
        print(x.model_dump_json(indent=2))
    print("\n=== META (no history) ===")
    print({k: v for k, v in meta.items() if k != "history"})
