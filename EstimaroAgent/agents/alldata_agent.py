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


def _build_task(job: JobSpec, vehicle: VehicleFingerprint,
                service_skeleton: dict | None = None) -> str:
    # Task #15 — deterministic labor-row selection. When the skeleton knows
    # which row this service "always" picks, inject it into the prompt as
    # the FIRST priority. Without this, the agent picks freely between
    # 'Front Pads' (0.9h) and 'Brake Pad and Rotor' (1.3h) on different
    # runs of the same VIN — same estimate, different numbers. With the
    # explicit priority list the same VIN+complaint produces the same row.
    preferred_block = ""
    if service_skeleton:
        pref = service_skeleton.get("labor_preferred")
        kws = service_skeleton.get("labor_keywords") or []
        if pref or kws:
            ranked = []
            seen = set()
            if pref:
                ranked.append(pref)
                seen.add(pref.lower())
            for k in kws:
                if k and k.lower() not in seen:
                    ranked.append(k)
                    seen.add(k.lower())
            preferred_block = f"""

PREFERRED LABOR ROW (read carefully):
  Pick the row whose name matches this priority list — try them IN ORDER.
  Only fall back to the next name if the previous one literally is not on
  the article. This keeps the SAME VIN + SAME complaint producing the
  SAME labor row across runs.
{chr(10).join(f'    {i+1}. {name!r}' for i, name in enumerate(ranked[:8]))}

  If NONE of these row names exist on the article, pick the row whose
  description best matches the customer symptom + subsystem above and
  set confidence <= 0.75 so downstream gating flags the picked row for
  advisor review.
"""

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
{preferred_block}
GOAL: On the ALLDATA "Parts and Labor" article page for the operation that best
matches the customer symptom, extract BOTH labor hours AND OEM parts.

NAVIGATION PLAN (use numbered overlays in screenshots):
  1. If you see REPAIR / ESTIMATOR tiles, click REPAIR.
  2. Pick the vehicle. The vehicle banner at the top of every subsequent
     page shows the year/make/model and ends with the VIN.

     A post-extraction VIN-suffix guard runs AFTER you finish, so do NOT
     use ask_human with "vehicle_mismatch" — that check is automated and
     catches wrong-vehicle picks reliably. Your job is just to navigate.

     Specifically: do NOT abort over what looks like a VIN difference.
     ALLDATA's banner contains MULTIPLE alphanumeric tokens — engine
     code (e.g. "B5244T3", "N20", "M52B28"), VIN position chars, the
     full 17-char VIN, sometimes a trim code. ONLY the 17-character
     string IS the VIN; the short codes are engine / trim identifiers.
     If you see a short alphanumeric like "B5244T3" that doesn't match
     the target VIN suffix, that's an ENGINE CODE not a VIN — proceed.

     Also do NOT abort over model-name differences:
       - NHTSA "V70"  → ALLDATA may show "XC70" or "V70 XC"  (same chassis)
       - NHTSA "3-Series" → ALLDATA may show "330i" or "F30"  (sub-trim)
       - NHTSA "C-Class"  → ALLDATA may show "C300 4MATIC"   (sub-variant)
     All of these are CORRECT — proceed.

     Use ask_human ONLY when you genuinely cannot reach a vehicle on
     the article (no VIN search worked, no Recent Vehicles entry, etc.).
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


async def _scan_repair_procedure(browser, article_url: str,
                                 history_urls: list[str] | None = None,
                                 side_hint: str | None = None) -> dict:
    """Navigate the live ALLDATA tab from the Parts-and-Labor article to
    the matching Service-and-Repair article, dump body text, and parse
    with the keyword-based parser.

    Two-step traversal — ALLDATA's SPA does NOT expose a direct
    repair-article URL from the parts-and-labor-article URL. R-cell
    clicks update Angular state, not the segment name. So:

      1) Parse <vehicle> and <component> ids out of the article URL,
         navigate to /vehicle/<v>/component/<c>/filter/repair — that's
         ALLDATA's component-page-filtered-to-repair-articles view, a
         LIST of repair article titles like "Removal and Replacement",
         "Overhaul", "Disassembly".

      2) Click the first link matching a known procedure title
         ("removal and replacement" is the canonical one for parts
         replacement jobs; "overhaul" / "service and repair" fall
         back). The SPA loads the actual repair-article body in place.

      3) Read body.innerText and pass to parse_repair_procedure.

    Falls back to a clear scan_status string on any failure — the
    worker treats absence of items as informational, never blocking
    the estimate.
    """
    import re
    import asyncio as _asyncio
    from services.repair_procedure_parser import parse_repair_procedure

    m = re.search(r"/parts-and-labor-article/(\d+)/component/(\d+)/itype/(\d+)/?", article_url)
    if not m:
        return {"items": [], "scan_status": "url_parse_failed",
                "tried_url": article_url}
    vehicle_id, parent_component, itype = m.group(1), m.group(2), m.group(3)

    # The article URL records the PARENT category component (e.g. 3077 for
    # Disc Brake System) — but the actual labor row sits under a LEAF
    # child (e.g. component 21 = Brake Pad). Parent categories' filter=
    # repair view is empty; only the leaf has a usable list of repair
    # articles. Recover the leaf component id from the agent's history
    # by finding the most recent /vehicle/<v>/component/<leaf>/filter/
    # <itype> URL (filter equals itype because that's how the agent
    # drilled into the article in step 7).
    leaf_component = parent_component
    if history_urls:
        leaf_pat = re.compile(
            rf"/vehicle/{vehicle_id}/component/(\d+)/filter/{itype}\b"
        )
        for url in reversed(history_urls):  # most-recent wins
            mm = leaf_pat.search(url or "")
            if mm and mm.group(1) != parent_component:
                leaf_component = mm.group(1)
                logger.info(
                    f"[R-cell] derived leaf component {leaf_component} "
                    f"from agent history (parent was {parent_component})"
                )
                break

    repair_list_url = (
        f"https://my.alldata.com/repair/#/vehicle/{vehicle_id}"
        f"/component/{leaf_component}/filter/repair"
    )

    try:
        page = await browser.find_tab_by_url("alldata.com")
        if page is None:
            return {"items": [], "scan_status": "no_alldata_tab",
                    "tried_url": repair_list_url}

        # Step 1: nav to the filter=repair list view for the same component
        try:
            await page.goto(repair_list_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return {"items": [], "scan_status": f"nav_failed: {str(e)[:120]}",
                    "tried_url": repair_list_url}
        await _asyncio.sleep(4)  # SPA hydration

        # Step 2: drill through ALLDATA's nested repair-procedure tree.
        # The hierarchy is usually 3 levels:
        #   level 1: list view  → 'Removal and Replacement', 'Overhaul', ...
        #   level 2: sub-list   → 'Brake Pads Front, Replacing', 'Brake Pads Rear, Replacing'
        #   level 3: ARTICLE    → actual procedure text/canvas
        # We may need to click twice. Use side_hint ('front'/'rear') to
        # disambiguate the level-2 choice when present; otherwise prefer
        # 'front' since most jobs are front-brake-leaning.
        click_trail = []
        DRILL_JS = """({order, side}) => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 5 || r.height < 5) return false;
                const cs = getComputedStyle(el);
                if (cs.visibility === 'hidden' || cs.display === 'none') return false;
                return true;
            };
            const els = Array.from(document.querySelectorAll('a, button, [role=link], [role=button]')).filter(visible);
            // Apply side preference first when caller passed one
            if (side) {
                for (const candidate of order) {
                    const hit = els.find(el => {
                        const t = (el.innerText || '').trim().toLowerCase();
                        return t.length > 0 && t.length < 80
                            && t.includes(candidate) && t.includes(side);
                    });
                    if (hit) { hit.click(); return {clicked: candidate, side_matched: true, text: (hit.innerText || '').trim().slice(0, 80)}; }
                }
            }
            // No side match — pick first candidate text-match
            for (const candidate of order) {
                const hit = els.find(el => {
                    const t = (el.innerText || '').trim().toLowerCase();
                    return t.length > 0 && t.length < 80 && t.includes(candidate);
                });
                if (hit) { hit.click(); return {clicked: candidate, side_matched: false, text: (hit.innerText || '').trim().slice(0, 80)}; }
            }
            return null;
        }"""

        level1_order = [
            "removal and replacement", "removal & replacement",
            "removal, installation", "removal and installation",
            "overhaul", "service and repair", "replacement",
        ]
        level2_order = [
            "replacing", "removing", "installing", "replacement",
            "removal", "service",
        ]

        # Normalise side hint
        side = (side_hint or "").strip().lower()
        if side not in ("front", "rear"):
            side = "front"  # default — Sergio's most common service

        # Level 1 click
        l1 = await page.evaluate(DRILL_JS, {"order": level1_order, "side": None})
        if not l1:
            return {"items": [], "scan_status": "no_procedure_link_found",
                    "tried_url": repair_list_url}
        click_trail.append({"level": 1, **l1})
        await _asyncio.sleep(4)

        # Level 2 (optional) — only when the page looks like another
        # sub-list (small number of short "Replacing"/"Removing" links,
        # short body). Otherwise the same link selector would match
        # individual procedure-step words on the article and wrongly
        # navigate away.
        is_sublist = await page.evaluate("""() => {
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 5 || r.height < 5) return false;
                const cs = getComputedStyle(el);
                if (cs.visibility === 'hidden' || cs.display === 'none') return false;
                return true;
            };
            const els = Array.from(document.querySelectorAll('a')).filter(visible);
            const hits = els.filter(el => {
                const t = (el.innerText || '').trim().toLowerCase();
                return t.length > 0 && t.length < 80
                    && (t.includes('replacing') || t.includes('removing')
                        || t.includes('installing') || t.includes('replacement'));
            });
            const bodyLen = (document.body && document.body.innerText || '').length;
            // Sub-list characteristics: 2-15 short procedure-y links AND
            // body shorter than ~1500 chars (article content would push it
            // higher even with canvas — at least breadcrumbs etc).
            return {sublist: hits.length >= 1 && hits.length <= 15 && bodyLen < 1500,
                    hits: hits.length, bodyLen: bodyLen};
        }""")
        logger.info(f"[R-cell] post-level-1 page: {is_sublist}")
        if isinstance(is_sublist, dict) and is_sublist.get("sublist"):
            l2 = await page.evaluate(DRILL_JS, {"order": level2_order, "side": side})
            if l2:
                click_trail.append({"level": 2, **l2})
                await _asyncio.sleep(4)
        # else: we're already on the article page — proceed

        clicked = click_trail[-1]  # most recent click for logging

        # Step 3: wait for article content to render. Try text DOM first
        # (works on the small minority of ALLDATA pages that DO expose
        # text), fall back to vision-LLM screenshot extraction for the
        # majority (canvas / anti-scraping protected pages).
        await _asyncio.sleep(5)
        body_text = await page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )
        clicked_text = clicked.get("text") if isinstance(clicked, dict) else None
        # Combined trail for diagnostics (e.g. "L1:Removal and Replacement -> L2:Brake Pads Front, Replacing")
        trail_str = " -> ".join(
            f"L{t.get('level')}:{t.get('text', '')[:50]}" for t in click_trail
        )

        # Path 1 — text DOM had real content (rare on ALLDATA but free
        # when it works, so we always try first).
        if body_text and len(body_text) >= 1500:
            parsed = parse_repair_procedure(body_text)
            parsed["scan_status"] = "ok_text"
            parsed["tried_url"] = page.url
            parsed["clicked_link"] = clicked_text
            logger.info(
                f"[R-cell text] parsed {len(parsed['items'])} replacement "
                f"items from {parsed['scanned_chars']} chars after clicking "
                f"{clicked!r}"
            )
            return parsed

        # Path 2 — text DOM blocked (canvas / anti-scrape). Screenshot
        # the full page and let Gemini Flash read the rendered procedure.
        # This adds ~10-20s + ~$0.002 per job but it's the only way
        # ALLDATA's modern article surface yields the renew/replace
        # instructions Sergio's manual workflow depends on.
        logger.info(
            f"[R-cell vision] text DOM returned {len(body_text)} chars "
            f"(below 1500 threshold) — falling back to screenshot + "
            f"Gemini vision extraction"
        )
        try:
            from core.gemini_client import GeminiClient
            from services.repair_procedure_parser import normalize_vision_items

            screenshot_bytes = await page.screenshot(full_page=True)
            shot_kb = len(screenshot_bytes) // 1024
            logger.info(f"[R-cell vision] captured {shot_kb} KB screenshot")

            gemini = GeminiClient()
            # extract_repair_items is sync (uses google-generativeai
            # which is sync under the hood). Run in a thread so we
            # don't block the asyncio loop.
            vision_items = await _asyncio.to_thread(
                gemini.extract_repair_items, screenshot_bytes
            )
            parsed = normalize_vision_items(vision_items or [])
            parsed["scan_status"] = "ok_vision"
            parsed["tried_url"] = page.url
            parsed["clicked_link"] = clicked_text
            parsed["screenshot_kb"] = shot_kb
            logger.info(
                f"[R-cell vision] Gemini returned {len(vision_items)} raw "
                f"items, normalised to {len(parsed['items'])} unique "
                f"replacement components"
            )
            return parsed
        except Exception as e:
            logger.warning(
                f"[R-cell vision] failed: {type(e).__name__}: {str(e)[:160]}"
            )
            return {
                "items": [], "scan_status": f"vision_failed: {type(e).__name__}",
                "tried_url": page.url,
                "clicked_link": clicked_text,
                "note": str(e)[:200],
            }
    except Exception as e:
        logger.warning(f"R-cell scan error: {type(e).__name__}: {str(e)[:160]}")
        return {"items": [], "scan_status": f"error: {type(e).__name__}",
                "tried_url": repair_list_url}


async def lookup_labor_time(
    job: JobSpec, vehicle: VehicleFingerprint, max_steps: int = 30,
    service_skeleton: dict | None = None,
) -> tuple[LaborResult | None, dict]:
    """Returns (labor, meta).  meta["parts"] holds the OEM parts list parsed
    from the same Parts and Labor page."""
    task = _build_task(job, vehicle, service_skeleton=service_skeleton)
    agent = VisionAgent(portal_url=ALLDATA_HOME, task=task, max_steps=max_steps,
                        login_portal="alldata")

    # Repair-Procedure scan (task #13) is folded into the same browser
    # context as the labor extraction: when the labor agent finishes
    # successfully we already have the ALLDATA tab parked on the
    # parts-and-labor-article page, so a sibling-URL navigation to the
    # repair-article variant + body-text dump is cheap and avoids
    # re-running the whole vision flow.
    repair_procedure_meta: dict = {"items": [], "scan_status": "not_attempted"}
    async with ChromeDebugBrowser() as browser:
        # Force-reset the ALLDATA tab to the vehicle selector before the
        # agent starts. Without this, a leftover deep-article URL (from
        # a previous run or a probe) leaves the agent staring at content
        # whose vehicle banner doesn't match — it then ask_human's on
        # what looks like a VIN mismatch (an engine code mis-read as a
        # VIN). Explicit nav guarantees the agent starts from a known
        # state every time.
        try:
            pre_page = await browser.find_tab_by_url("alldata.com")
            if pre_page is not None:
                await pre_page.goto(
                    "https://my.alldata.com/repair/#/select-vehicle",
                    wait_until="domcontentloaded", timeout=20000,
                )
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[alldata] pre-run reset to /select-vehicle failed: {e}")
        result = await agent.run(browser)
        # Best result NOW so we can pick the article URL while the
        # browser is still alive for the R-cell scan.
        if result["extracted"]:
            try:
                best_for_url = max(result["extracted"],
                                   key=lambda e: e.get("confidence", 0.0))
                article_url = (best_for_url.get("url_at_decision") or "").strip()
                if "/parts-and-labor-article/" in article_url:
                    # Pass every URL the agent visited so the scanner can
                    # recover the LEAF component (article URL only has
                    # parent category; leaf is in step-N history).
                    history_urls = [
                        (h.get("url_at_decision") or "")
                        for h in (result.get("history") or [])
                    ]
                    # Derive side hint from JobSpec so the level-2 picker
                    # ('Brake Pads Front, Replacing' vs 'Rear, Replacing')
                    # matches the customer's actual job.
                    job_text = " ".join([
                        (job.subsystem or ""),
                        (job.symptom or ""),
                        " ".join(job.keywords or []),
                    ]).lower()
                    side_hint = "rear" if "rear" in job_text else "front"
                    repair_procedure_meta = await _scan_repair_procedure(
                        browser, article_url,
                        history_urls=history_urls,
                        side_hint=side_hint,
                    )
                else:
                    repair_procedure_meta["scan_status"] = (
                        f"no_pnl_article_url (got {article_url[:80]!r})"
                    )
            except Exception as e:
                logger.warning(f"R-cell scan setup failed: {e}")
                repair_procedure_meta["scan_status"] = f"setup_error: {str(e)[:120]}"

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

    # Task #15 — deterministic-row match check. Compare the extracted
    # operation against the skeleton's labor_keywords priority list. If
    # the agent picked the labor_preferred row → high signal. If a
    # later-priority match → still OK but mark unpreferred. If NONE of
    # the listed rows → off-script extraction, cap confidence so
    # downstream gating routes it to advisor review. This is what
    # eliminates the 0.9h-vs-1.3h variance the Volvo brake test
    # produced across runs.
    determinism_status = "no_skeleton"
    determinism_rank = None
    if service_skeleton:
        op_lc = (labor.operation or "").lower().strip()
        pref = (service_skeleton.get("labor_preferred") or "").lower().strip()
        kws_lc = [
            (k or "").lower().strip()
            for k in (service_skeleton.get("labor_keywords") or [])
            if k
        ]
        # Build a single priority list with preferred at position 0
        priority = []
        if pref:
            priority.append(pref)
        for k in kws_lc:
            if k and k not in priority:
                priority.append(k)

        matched_at = None
        for idx, kw in enumerate(priority):
            if kw and (kw in op_lc or op_lc in kw):
                matched_at = idx
                break

        if matched_at is None:
            determinism_status = "off_script"
            determinism_rank = None
            # Cap extraction_confidence at 0.7 so the confidence-gate
            # routes this estimate to advisor_review tier rather than
            # auto-approve. The agent picked a row that's not on the
            # canonical priority list — could be legitimate (unusual
            # job phrasing) or wrong (misclassified row).
            current_conf = float(best.get("confidence", 0.0))
            if current_conf > 0.7:
                best["confidence"] = 0.7
            logger.warning(
                f"[determinism] extracted operation {labor.operation!r} "
                f"matches NONE of skeleton priority {priority[:4]!r} — "
                f"capping confidence to 0.7 for advisor review"
            )
        elif matched_at == 0:
            determinism_status = "matched_preferred"
            determinism_rank = 0
            logger.info(
                f"[determinism] extracted {labor.operation!r} matched "
                f"PREFERRED row at priority 0 — deterministic pick"
            )
        else:
            determinism_status = "matched_fallback"
            determinism_rank = matched_at
            logger.info(
                f"[determinism] extracted {labor.operation!r} matched "
                f"fallback row at priority {matched_at} — non-preferred "
                f"but on-list"
            )

    return labor, {
        "agent_run": result,
        "verification": verification.model_dump(),
        "extraction_confidence": best.get("confidence", 0.0),
        "parts": [p.model_dump() for p in parts],
        "section_path": section_path,
        # Task #13 — repair procedure scan output. Items list may be empty
        # when ALLDATA's R-cell didn't load, the URL wasn't transformable,
        # or no replacement keywords fired. scan_status carries the reason.
        "repair_procedure": repair_procedure_meta,
        # Task #15 — determinism signal. status ∈ {matched_preferred,
        # matched_fallback, off_script, no_skeleton}. rank is the
        # priority index of the matched row (0 = preferred). FE shows
        # a small badge on the labor row so the advisor sees whether
        # this estimate's labor pick is the canonical one for this
        # service type.
        "determinism": {
            "status": determinism_status,
            "rank": determinism_rank,
            "preferred": service_skeleton.get("labor_preferred") if service_skeleton else None,
            "default_hours": service_skeleton.get("labor_default_hours") if service_skeleton else None,
        },
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
