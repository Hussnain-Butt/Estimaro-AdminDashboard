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


def _build_task(search_query: str, expected_part: Optional[str]) -> str:
    expect = f'\n  Expected part (for matching): {expected_part}' if expected_part else ""
    return f"""
You are inside the SSF (Eurolink) parts shop. The shop is already logged in.

SEARCH FOR: "{search_query}"{expect}

There is a "Search Part Number" box near the top of the page. It takes an OEM /
part number and returns matching parts with price and availability.

NAVIGATION PLAN (use the numbered overlays in the screenshots):
  1. Click the "Search Part Number" text box, type EXACTLY: {search_query}
  2. Press Enter (or click the search/magnifier button next to it).
  3. Wait for the results to load. Each result typically shows a BRAND / LINE,
     a PART NUMBER, a DESCRIPTION, a PRICE, and an AVAILABILITY / stock column
     (e.g. "In Stock", a quantity, or a branch/ETA).
  4. If the part number is not a valid SSF number and nothing is found, that is
     an acceptable result — report it (do not invent data).

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "search_term": "{search_query}",
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
  * If the search returns no products, confidence < 0.6 and action="ask_human"
    with the exact message SSF showed.
"""


async def lookup(
    search_query: str,
    *,
    expected_part: Optional[str] = None,
    max_steps: int = 18,
    timeout: int = 240,
) -> Tuple[list[VendorQuote], dict]:
    """Search SSF by part number. Returns (quotes, meta) — one VendorQuote per row."""
    task = _build_task(search_query, expected_part)
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
    # On the VPS, run against the logged-in session with a real SSF/OEM number.
    q = "0084201520"  # example Mercedes-style brake pad number; replace as needed
    quotes, meta = asyncio.run(lookup(q))
    print("\n=== QUOTES ===")
    for x in quotes:
        print(x.model_dump_json(indent=2))
    print("\n=== META (no history) ===")
    print({k: v for k, v in meta.items() if k != "history"})
