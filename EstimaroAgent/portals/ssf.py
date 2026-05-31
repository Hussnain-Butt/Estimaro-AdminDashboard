"""SSF (Eurolink) vendor agent.

SSF Auto Parts is a European-parts distributor. Its shop has a "Search Part
Number" box that takes an OEM/part number and returns matching parts with the
shop's price and availability — one of the real price+stock sources for the
estimate. (A "Find by VIN" path also exists for catalogue browsing.)
"""
import asyncio
from typing import Optional, Tuple

from loguru import logger

from core.browser import ChromeDebugBrowser
from models.job_spec import VendorQuote
from portals.base import run_portal_agent


PORTAL_NAME = "SSF"
PORTAL_URL = "https://shop.ssfautoparts.com/Catalog"

# Stable selectors for SSF Catalog toolbar (verified 2026-05-30). The
# vision-agent can't fill them because they sit inside Select2 wrappers — we
# drive them deterministically and hand off to the agent only for extraction.
SEL_VIN_INPUT = "#vinSearchInput"
SEL_KEYWORD_INPUT = "#keywordSearchInput"
SEL_PT_DROPDOWN_BTN = "#partTypeDropdownFromKeywordId"

# SSF's keyword search matches a controlled part-type vocabulary. Qualifiers
# like "front"/"rear"/"left"/"right" don't appear in the part-type names, so
# we strip them before submitting and rely on the part-type picker (or a
# narrower search) to disambiguate front vs rear when both exist.
_QUALIFIER_WORDS = {"front", "rear", "left", "right", "lh", "rh",
                    "driver", "passenger", "side", "upper", "lower"}


def _normalize_keyword(part_type: str) -> str:
    tokens = [t for t in part_type.lower().split() if t not in _QUALIFIER_WORDS]
    return " ".join(tokens).strip() or part_type


def _build_task(vehicle, part_type: str, oem_hint: Optional[str]) -> str:
    hint = f'\n  OEM number hint (for matching only): {oem_hint}' if oem_hint else ""
    return f"""
You are inside the SSF (Eurolink) parts shop. The shop is already logged in,
the vehicle has ALREADY been set from VIN {vehicle.vin} ({vehicle.year}
{vehicle.make} {vehicle.model}), and the keyword "{part_type}" has ALREADY
been submitted. The page should be showing the SEARCH RESULTS LIST for
"{part_type}".

YOUR ONLY JOB: read the visible results and emit the extraction JSON.{hint}

WHAT YOU MAY SEE:
  A. A results table / list of part rows — each row has brand/line, part
     number, description, price, and an availability / stock indicator.
     EXTRACT these rows (up to 6).
  B. A "Select Part Type" or "Part Type" dropdown asking you to refine the
     keyword (SSF sometimes maps a keyword to several part types — e.g.
     "brake pads" → "Brake Pad Set (Front)", "Brake Pad Set (Rear)"). If so,
     click the FRONT option matching the part_type (or whichever matches
     "{part_type}" most closely), then extract the rows that appear.
  C. "No results" / empty list. Click the "Catalog" tab in the top toolbar,
     navigate Brakes → Brake Pads via the category tree (use action="find"
     for any category text not in view), and extract rows from there.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "vehicle": "<vehicle text shown in the toolbar/results header>",
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
  * Report only rows actually visible — never invent prices.
  * price = numeric your/buy price if shown, else null.
  * in_stock = true if availability indicates stock on hand, false if out of
    stock / special order, null if unclear.
  * Capture up to the first 6 result rows.
  * Only use action="ask_human" if you cannot reach a results list after
    genuinely trying both (B) and (C).

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


async def _prep_search(vehicle, part_type: str) -> Optional[str]:
    """Deterministically set VIN + submit keyword on the SSF Catalog page.

    Returns None on success, or a categorised error string on failure.
    """
    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus(PORTAL_URL, url_match="ssfautoparts")
            await page.wait_for_selector(SEL_VIN_INPUT, timeout=15_000)

            current_vin = (await page.input_value(SEL_VIN_INPUT)).strip().upper()
            if current_vin != vehicle.vin.strip().upper():
                await page.fill(SEL_VIN_INPUT, "")
                await page.fill(SEL_VIN_INPUT, vehicle.vin)
                await page.press(SEL_VIN_INPUT, "Enter")
                # SSF takes a moment to decode + populate Make/Model/Year selects
                await asyncio.sleep(4)

            await page.wait_for_selector(SEL_KEYWORD_INPUT, timeout=10_000)
            keyword = _normalize_keyword(part_type)
            await page.fill(SEL_KEYWORD_INPUT, "")
            await page.fill(SEL_KEYWORD_INPUT, keyword)
            await page.press(SEL_KEYWORD_INPUT, "Enter")
            await asyncio.sleep(5)

            # If SSF rejected the keyword outright, surface it as a clean error.
            body = await page.evaluate("() => document.body.innerText || ''")
            if "no part type found" in body.lower():
                return f"no_part_type :: SSF keyword vocabulary has no match for {keyword!r}"

            # If the part-type dropdown still says "Part Type" (unselected) and
            # no prices are visible, multiple part types matched the keyword —
            # pick the option whose text best matches the requested part_type.
            btn_text = await page.evaluate(
                f"() => (document.querySelector('{SEL_PT_DROPDOWN_BTN}')?.innerText || '').trim()"
            )
            has_prices = "$" in body and any(c.isdigit() for c in body)
            if btn_text.lower() == "part type" and not has_prices:
                picked = await _pick_part_type(page, part_type)
                if picked is None:
                    return "part_type_pick_failed :: dropdown opened but no option matched"
                await asyncio.sleep(5)
    except Exception as e:
        logger.error(f"[{PORTAL_NAME}] prep_search failed: {type(e).__name__}: {e}")
        return f"prep_failed :: {type(e).__name__}: {str(e)[:160]}"
    return None


async def _pick_part_type(page, requested: str) -> Optional[str]:
    """Open the part-type dropdown and click the option best matching `requested`.

    Returns the picked option text on success, None if no option could be picked.
    Matching: prefer options whose text contains the most words from `requested`,
    with a tiebreaker preferring entries qualified as 'front' when the caller
    asked for a front part, and 'rear' when they asked for a rear one.
    """
    await page.click(SEL_PT_DROPDOWN_BTN)
    await asyncio.sleep(1)
    req_lower = requested.lower()
    prefer_front = "front" in req_lower
    prefer_rear = "rear" in req_lower
    req_words = [w for w in req_lower.split() if w not in _QUALIFIER_WORDS]

    picked = await page.evaluate(
        """([reqWords, preferFront, preferRear]) => {
  const cand = [];
  document.querySelectorAll('a,li,button,div').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 5 || r.height < 5 || r.height > 60) return;
    const t = (el.innerText || '').trim();
    if (!t || t.length > 80) return;
    // dropdown options live below the keyword button (y > 160 in our viewport)
    if (r.y < 160) return;
    cand.push({el, t, y: r.y});
  });
  if (!cand.length) return null;
  const score = c => {
    const tl = c.t.toLowerCase();
    let s = reqWords.reduce((acc, w) => acc + (tl.includes(w) ? 1 : 0), 0);
    if (preferFront && /front/i.test(c.t)) s += 0.5;
    if (preferRear && /rear/i.test(c.t)) s += 0.5;
    return s;
  };
  cand.sort((a, b) => score(b) - score(a) || a.y - b.y);
  const best = cand[0];
  if (score(best) === 0) return null;
  best.el.click();
  return best.t;
}""",
        [req_words, prefer_front, prefer_rear],
    )
    return picked


async def lookup(
    vehicle,
    part_type: str,
    *,
    oem_hint: Optional[str] = None,
    max_steps: int = 12,
    timeout: int = 180,
) -> Tuple[list[VendorQuote], dict]:
    """Set vehicle + keyword deterministically, then extract results via agent."""
    # login_portal="ssf" inside run_portal_agent re-validates session, but we
    # also need it BEFORE the deterministic prep step, so call it directly.
    from portals.auth import ensure_logged_in
    status = await ensure_logged_in("ssf")
    if not status.get("ok"):
        return [], {"error": f"login_failed :: {status.get('error') or status.get('action')}",
                    "history": [], "steps_taken": 0, "login_status": status}

    prep_err = await _prep_search(vehicle, part_type)
    if prep_err:
        return [], {"error": prep_err, "history": [], "steps_taken": 0}

    task = _build_task(vehicle, part_type, oem_hint)
    # login_portal="ssf" arms the mid-flight session watchdog in the agent;
    # initial_check=False because we already ran ensure_logged_in above.
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal="ssf",
                                       initial_check=False)
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
