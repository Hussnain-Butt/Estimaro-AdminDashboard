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

# Vehicle picker selectors (verified 2026-05-30 on a paid Worldpac account):
#   * The visible current-vehicle chip on the catalog header is a BUTTON
#     containing a DIV.vehicle-description with text like "2015 Mercedes-Benz
#     SLK250". Clicking it expands an in-page picker on the left panel.
#   * Inside the picker the catalog tree gives way to a 3-tab drill — Year
#     (#year-tab), Make (#make-tab), Model (#model-tab). The tabs render a
#     grid of clickable LI/BUTTON cells with the year/make/model text.
#   * "Vehicle History" on the right of the picker is a list of recent picks
#     (DIV.MuiListItem-root containing text like "2023 Mercedes-Benz C300
#     Base 2.0 L4"). When the target vehicle has been used before the picker
#     is a one-click select; otherwise the Y/M/M drill is the cold path.
#   * Worldpac doesn't offer a free-form VIN input here — only plate + state,
#     Year/Make/Model, and history. We rely on the NHTSA-decoded vehicle's
#     year/make/model to drive the drill.
SEL_VEHICLE_PILL = "button:has(.vehicle-description)"
SEL_VEHICLE_DESC = ".vehicle-description"
SEL_YEAR_TAB = "#year-tab"
SEL_MAKE_TAB = "#make-tab"
SEL_MODEL_TAB = "#model-tab"
# SpeedDIAL 2.0's vehicle picker DOES have a VIN field (`<input id="vin">`) —
# the old "Worldpac has no VIN input" note was outdated. Filling it + Enter sets
# the exact vehicle, far more reliably than the Year/Make/Model drill (whose
# model grid is flaky and whose labels — "C300" — don't match NHTSA's
# "C-Class"). We use VIN as the PRIMARY path and keep Y/M/M as a fallback.
SEL_VIN_INPUT = "#vin"

# Customer-complaint vocabulary → the canonical part-type label Worldpac's
# catalog lists in its right-side "Part Type" panel. Keys are matched
# loosely (substring, case-insensitive) so "Front Pads", "Brake Pad Set
# (Front)", "brake pads" all reach the same Worldpac row.
# Each entry: (regex to match the user request, Worldpac catalog label for the
# part-type checkbox, Worldpac sub-category that owns it in the left tree).
# Clicking the sub-category triggers Worldpac to populate the right-side
# "Selected Part Types" panel — without that step the checkbox row simply
# doesn't render after a fresh vehicle switch.
# Each entry: (regex matching the user request, Worldpac part-type label on
# the checkbox row, sub-category that contains it in the left tree, parent
# group that may need expanding first). After a fresh vehicle switch most
# parent groups are collapsed, so we click the parent group → wait → click
# the sub-category → wait → look for the checkbox row.
_LABEL_MAP = [
    (r"brake\s*pad",                 "Brake Pad Set",     "Brake Disc",   "Brake"),
    (r"\bpads?\b",                   "Brake Pad Set",     "Brake Disc",   "Brake"),
    (r"brake\s*(disc|rotor)",        "Brake Disc",        "Brake Disc",   "Brake"),
    (r"\brotors?\b",                 "Brake Disc",        "Brake Disc",   "Brake"),
    (r"brake\s*caliper",             "Brake Caliper",     "Brake Hydraulic", "Brake"),
    (r"\bcalipers?\b",               "Brake Caliper",     "Brake Hydraulic", "Brake"),
    (r"oil\s*filter",                "Oil Filter",        "Lubrication",  "Engine"),
    (r"air\s*filter",                "Air Filter",        "Air Intake",   "Engine"),
    (r"cabin\s*filter|cabin\s*air",  "Cabin Air Filter",  "Climate Control", "Climate Control"),
    (r"spark\s*plug",                "Spark Plug",        "Ignition",     "Engine"),
    (r"control\s*arm",               "Control Arm",       "Suspension",   "Suspension"),
    (r"shock",                       "Shock Absorber",    "Suspension",   "Suspension"),
    (r"strut",                       "Strut Assembly",    "Suspension",   "Suspension"),
    (r"wheel\s*bearing",             "Wheel Bearing",     "Suspension",   "Suspension"),
]


def _worldpac_label(part_type: str) -> Optional[str]:
    """Map a free-text part request to Worldpac's catalog label."""
    if not part_type:
        return None
    t = part_type.lower()
    for entry in _LABEL_MAP:
        if re.search(entry[0], t):
            return entry[1]
    return None


def _worldpac_category(part_type: str) -> tuple[Optional[str], Optional[str]]:
    """Return (sub_category, parent_group) for the part_type. After a fresh
    vehicle switch the parent group is usually collapsed and we need to
    expand it before the sub-category becomes clickable."""
    if not part_type:
        return None, None
    t = part_type.lower()
    for entry in _LABEL_MAP:
        if re.search(entry[0], t):
            return entry[2], entry[3]
    return None, None


async def _click_category(page, category: str, timeout_ms: int = 6000) -> bool:
    """Click a Worldpac top-level category tree node.

    We scope the selector to `.sd-category-node-level-1` so the parent
    group is unambiguous (only one level-1 LI named "Brake"; sub-categories
    like "Brake Booster" / "Brake Disc" carry level-2 and don't match).
    A Playwright `.click()` is used rather than a JS `el.click()` because
    Worldpac's React onClick handler needs the synthetic event a real
    Playwright click dispatches — a bare DOM click was a no-op in testing.
    """
    try:
        loc = page.locator(
            f".sd-category-node-level-1:has-text({category!r})"
        ).first
        if await loc.count() == 0:
            return False
        await loc.scroll_into_view_if_needed(timeout=2000)
        await loc.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


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


def _normalize_make(make: Optional[str]) -> str:
    """Worldpac shows makes in mixed forms (e.g. "Mercedes-Benz" with a hard
    hyphen, sometimes "Mercedes Benz" or all-uppercase). Strip non-alphanum
    so a substring compare against vehicle.make is forgiving."""
    if not make:
        return ""
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", make.lower())


async def _read_current_vehicle(page) -> Optional[str]:
    """Return the plain-text label Worldpac shows in its current-vehicle pill,
    or None if no vehicle is currently selected."""
    try:
        loc = page.locator(SEL_VEHICLE_DESC).first
        if await loc.count() == 0:
            return None
        return (await loc.inner_text(timeout=3000)).strip()
    except Exception:
        return None


def _model_fragments(vehicle) -> list[str]:
    """Token-level alphanumeric chunks (3+ chars) derived from the model
    AND trim. NHTSA model values like "C-Class" / "SLK-Class" are split on
    hyphens, and the trim ("C300", "SLK250") is mixed in so a Worldpac
    label rendered as "2015 Mercedes-Benz SLK250" still matches against
    NHTSA's "SLK-Class" model — via the "slk" fragment or the trim itself."""
    import re as _re
    seen: set[str] = set()
    out: list[str] = []
    for text in (getattr(vehicle, "model", None), getattr(vehicle, "trim", None)):
        if not text:
            continue
        for chunk in _re.split(r"[\s\-/]+", str(text).lower()):
            chunk = chunk.strip()
            if len(chunk) >= 3 and chunk not in seen:
                seen.add(chunk)
                out.append(chunk)
    return out


def _vehicle_matches(current: Optional[str], vehicle) -> bool:
    """Loose match — Worldpac's label and our NHTSA decode rarely line up
    exactly on trim/engine. We require the year AND a substring of the
    make AND any model/trim fragment to all be present."""
    if not current or not vehicle.year or not vehicle.make:
        return False
    cur_norm = _normalize_make(current)
    if str(vehicle.year) not in current:
        return False
    if _normalize_make(vehicle.make) not in cur_norm:
        return False
    fragments = _model_fragments(vehicle)
    if fragments:
        current_lower = current.lower()
        if not any(f in current_lower or f in cur_norm for f in fragments):
            return False
    return True


async def _click_history_match(page, vehicle) -> bool:
    """If the target year+make appears in the picker's "Vehicle History" panel,
    click the matching row. Returns True on success."""
    needle_year = str(vehicle.year)
    needle_make = _normalize_make(vehicle.make)
    fragments = _model_fragments(vehicle)
    try:
        items = page.locator(".MuiListItem-root")
        n = await items.count()
        for i in range(min(n, 25)):
            txt = (await items.nth(i).inner_text()).strip()
            txt_lower = txt.lower()
            txt_norm = _normalize_make(txt)
            if needle_year not in txt:
                continue
            if needle_make not in txt_norm:
                continue
            # Worldpac's history rows are formatted like
            # "2023 Mercedes-Benz C300 Base 2.0 L4", so the NHTSA model
            # ("C-Class") doesn't appear verbatim. Match via the same
            # alphanumeric fragments we use to compare the active vehicle.
            if fragments and not any(f in txt_lower or f in txt_norm for f in fragments):
                continue
            await items.nth(i).click(timeout=4000)
            return True
    except Exception as e:
        logger.warning(f"[{PORTAL_NAME}] history scan failed: {e}")
    return False


async def _drill_ymm(page, vehicle) -> Optional[str]:
    """Cold-path: pick the vehicle via the Year → Make → Model tabs.
    Returns None on success, error string on failure."""
    if not (vehicle.year and vehicle.make and vehicle.model):
        return "ymm_missing :: NHTSA decode lacks year+make+model"

    # Year tab is usually the default after opening the picker; click it
    # anyway to be safe.
    try:
        await page.click(SEL_YEAR_TAB, timeout=4000)
        await asyncio.sleep(0.4)
    except Exception:
        pass
    try:
        await page.locator(
            f":is(button, li, a, div):text-is('{vehicle.year}')"
        ).first.click(timeout=5000)
    except Exception as e:
        return f"year_pick_failed :: {type(e).__name__}: {str(e)[:120]}"
    await asyncio.sleep(0.8)

    # Worldpac typically auto-advances to the Make tab after a year click,
    # but the manual click is harmless if it's already there.
    try:
        await page.click(SEL_MAKE_TAB, timeout=2500)
        await asyncio.sleep(0.4)
    except Exception:
        pass
    make_chunks = [c for c in _normalize_make(vehicle.make).split() if c]
    try:
        # Try exact text first (handles "Mercedes-Benz" with hyphen), then
        # a contains-text fallback for spacing/case differences.
        try:
            await page.locator(
                f":is(button, li, a, div):text-is('{vehicle.make}')"
            ).first.click(timeout=4000)
        except Exception:
            await page.locator(
                f":is(button, li, a, div):has-text('{vehicle.make}')"
            ).first.click(timeout=4000)
    except Exception as e:
        return f"make_pick_failed :: {type(e).__name__}: {str(e)[:120]}"
    await asyncio.sleep(0.8)

    try:
        await page.click(SEL_MODEL_TAB, timeout=2500)
        await asyncio.sleep(0.4)
    except Exception:
        pass
    # vehicle.model is often "C-Class" / "SLK-Class" while Worldpac lists trims
    # like "C300" / "SLK250". Prefer the first matching by inner_text containing
    # any 3+ char chunk of model OR trim.
    chunks = _model_fragments(vehicle) or [str(vehicle.model or "").strip()]
    last_err: Optional[Exception] = None
    for chunk in chunks:
        try:
            await page.locator(
                f":is(button, li, a, div):has-text('{chunk}')"
            ).first.click(timeout=4000)
            await asyncio.sleep(2)
            return None
        except Exception as e:
            last_err = e
            continue
    return f"model_pick_failed :: {type(last_err).__name__ if last_err else 'NoMatch'}"


async def _set_vehicle_by_vin(page, vehicle) -> Optional[str]:
    """Set the catalog vehicle by typing the VIN into the picker's VIN field
    and pressing Enter. Returns None on success-ish (caller verifies the pill),
    or a short reason string when the VIN path isn't usable."""
    vin = (getattr(vehicle, "vin", "") or "").strip()
    if len(vin) < 11:
        return "no_vin"
    try:
        # The VIN field lives inside the picker; open it only if not already shown.
        if await page.locator(SEL_VIN_INPUT).count() == 0:
            try:
                await page.locator(SEL_VEHICLE_PILL).first.click(timeout=5000)
                await asyncio.sleep(2)
            except Exception:
                pass
        vin_in = page.locator(SEL_VIN_INPUT).first
        if await vin_in.count() == 0:
            return "no_vin_field"
        await vin_in.scroll_into_view_if_needed(timeout=3000)
        await vin_in.fill("")
        await vin_in.fill(vin)
        await vin_in.press("Enter")
        await asyncio.sleep(3.5)
        return None
    except Exception as e:
        logger.warning(f"[{PORTAL_NAME}] VIN set failed: {e}")
        return f"vin_set_error :: {type(e).__name__}: {str(e)[:80]}"


async def _ensure_vehicle(page, vehicle) -> Optional[str]:
    """Make sure Worldpac's current vehicle matches `vehicle`. Returns None
    on success or a categorised error string."""
    current = await _read_current_vehicle(page)
    if _vehicle_matches(current, vehicle):
        return None
    logger.info(
        f"[{PORTAL_NAME}] current vehicle {current!r} doesn't match target "
        f"{vehicle.year} {vehicle.make} {vehicle.model} — switching"
    )
    # A fresh reload clears any half-open picker state a previous failed run
    # may have left behind. Without this the vehicle pill click sometimes
    # toggles a stale popover shut instead of opening the picker, and the
    # history list ends up empty.
    try:
        await page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)
    except Exception:
        pass

    # PRIMARY: set by VIN (reliable). A VIN uniquely identifies the vehicle, so
    # the resulting pill only needs to agree on YEAR + MAKE — we must NOT apply
    # the full model check here, because NHTSA decodes the model as a class
    # ("C-Class") while Worldpac's pill shows the trim ("C300"), so
    # _vehicle_matches would wrongly reject a correct VIN result.
    vin_err = await _set_vehicle_by_vin(page, vehicle)
    if vin_err is None:
        new = await _read_current_vehicle(page)
        if (new and str(vehicle.year) in new
                and _normalize_make(vehicle.make) in _normalize_make(new)):
            logger.info(f"[{PORTAL_NAME}] vehicle switched via VIN → {new!r}")
            return None
        logger.info(f"[{PORTAL_NAME}] VIN set didn't match (got {new!r}); "
                    f"falling back to history / Y-M-M")
    else:
        logger.info(f"[{PORTAL_NAME}] VIN path unavailable ({vin_err}); "
                    f"falling back to history / Y-M-M")

    # FALLBACK: open the picker and use history match or the Year/Make/Model drill.
    try:
        await page.locator(SEL_VEHICLE_PILL).first.click(timeout=5000)
    except Exception as e:
        return f"picker_open_failed :: {type(e).__name__}: {str(e)[:120]}"
    await asyncio.sleep(2)

    if await _click_history_match(page, vehicle):
        await asyncio.sleep(3)
        new = await _read_current_vehicle(page)
        if _vehicle_matches(new, vehicle):
            logger.info(f"[{PORTAL_NAME}] vehicle switched via history → {new!r}")
            return None
        # History click landed somewhere else — fall through to Y/M/M.

    err = await _drill_ymm(page, vehicle)
    if err:
        return err
    new = await _read_current_vehicle(page)
    if not _vehicle_matches(new, vehicle):
        return f"ymm_post_check_failed :: ended on {new!r}"
    logger.info(f"[{PORTAL_NAME}] vehicle switched via Y/M/M → {new!r}")
    return None


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

            # Make sure the catalog's current vehicle is the one we want —
            # otherwise the part-type checkboxes don't render for our VIN
            # and `row_not_found` would fire below for the wrong reason.
            veh_err = await _ensure_vehicle(page, vehicle)
            if veh_err:
                return f"vehicle_set_failed :: {veh_err}", label
            # The picker collapses back to the category tree after a vehicle
            # change; give the catalog a moment to render the new part-type
            # list before we look for our row.
            await asyncio.sleep(2)

            # The right-side "Selected Part Types" panel is empty after a
            # fresh vehicle switch and the parent group in the left tree is
            # usually collapsed. Clicking the parent group (e.g. "Brake")
            # both expands its sub-categories AND populates the right panel
            # with every part-type in the group — which includes our row.
            # The narrower sub-category (e.g. "Brake Disc") is a UX filter
            # but isn't required for the row to render, so we keep this
            # one-click and let the scroll-into-view in the row selector
            # below pick the right entry out of the alphabetical list.
            _sub_cat, parent_grp = _worldpac_category(part_type)
            if parent_grp:
                clicked = await _click_category(page, parent_grp)
                if not clicked:
                    logger.info(
                        f"[{PORTAL_NAME}] parent group {parent_grp!r} not "
                        f"clickable; relying on whatever panel state exists"
                    )
                await asyncio.sleep(2.5)

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
    # login_portal="worldpac" arms the mid-flight session watchdog in the agent;
    # initial_check=False because we already ran ensure_logged_in above.
    raw, meta = await run_portal_agent(PORTAL_URL, task, max_steps=max_steps,
                                       timeout=timeout, login_portal="worldpac",
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
