"""Estimaro Agent Worker.

Polls the Railway backend for queued auto-generate jobs, runs the full
Hermes -> NHTSA -> ALLDATA agent pipeline, posts result back.

Run as a systemd service `estimaro-agent.service`.
"""
import asyncio
import os
import socket
import sys
import time
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from config import settings
from core.hermes_client import HermesClient
from core.browser import ChromeDebugBrowser
from services.nhtsa_service import decode_vin
from agents.alldata_agent import lookup_labor_time, ALLDATA_HOME
from models.job_spec import JobSpec


BACKEND_URL = settings.BACKEND_URL.rstrip("/")
WORKER_SECRET = os.environ.get("AGENT_WORKER_SECRET", "change-me-in-prod")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
POLL_INTERVAL = max(3, int(settings.BACKEND_POLL_INTERVAL))
# Hard upper bound for a single job so a hung Gemini/Hermes/Playwright call
# can never block the worker forever. Backend's stale-recovery uses a longer
# window (15 min), so this should always trip first on a genuine hang.
JOB_TIMEOUT = int(os.environ.get("AGENT_JOB_TIMEOUT", "480"))  # seconds


def _headers():
    return {"X-Worker-Secret": WORKER_SECRET}


async def _claim_next(client: httpx.AsyncClient) -> Optional[dict]:
    try:
        r = await client.get(
            f"{BACKEND_URL}/api/v1/auto-generate/jobs/pending/next",
            params={"worker_id": WORKER_ID},
            headers=_headers(),
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code in (204,):
            return None
    except Exception as e:
        logger.warning(f"claim error: {e}")
    return None


async def _post_progress(client: httpx.AsyncClient, job_id: str, msg: str, pct: int):
    try:
        await client.post(
            f"{BACKEND_URL}/api/v1/auto-generate/jobs/{job_id}/progress",
            headers=_headers(),
            json={"progress": msg, "progress_pct": pct},
            timeout=15,
        )
    except Exception as e:
        logger.warning(f"progress post failed: {e}")


async def _post_result(client: httpx.AsyncClient, job_id: str, result: dict):
    r = await client.post(
        f"{BACKEND_URL}/api/v1/auto-generate/jobs/{job_id}/result",
        headers=_headers(),
        json={"result": result},
        timeout=30,
    )
    r.raise_for_status()


async def _post_failure(client: httpx.AsyncClient, job_id: str, err: str):
    try:
        await client.post(
            f"{BACKEND_URL}/api/v1/auto-generate/jobs/{job_id}/fail",
            headers=_headers(),
            json={"error": err},
            timeout=15,
        )
    except Exception as e:
        logger.warning(f"failure post failed: {e}")


async def _reset_to_vehicle_selector() -> bool:
    """Force the live ALLDATA tab back to the vehicle selector before each job.

    Returns True when the page actually landed on `/select-vehicle` after
    navigation. Returns False if ALLDATA redirected somewhere unexpected
    (e.g. session expired -> login page, account error page) — the caller
    can use this to fail fast instead of running the agent against the
    wrong starting state and burning 25 steps on a doomed run.
    """
    target = "https://my.alldata.com/repair/#/select-vehicle"
    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus(target)
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"reset navigation failed: {e}")
                return False
            # Verify we actually landed on the vehicle selector. ALLDATA will
            # redirect to login if the session dropped between the auth check
            # and now, and to an account/error page if the subscription has
            # lapsed; in both cases the agent's vehicle-pick prompt cannot
            # succeed and we should surface the real reason.
            if "select-vehicle" not in page.url:
                logger.warning(f"reset landed on unexpected URL: {page.url}")
                return False
            return True
    except Exception as e:
        logger.warning(f"reset_to_vehicle_selector outer error: {e}")
        return False


def _normalize_oem(s) -> str:
    """OEM numbers come back from each portal with different formatting
    (`0074209220` vs `007 420 92 20` vs `OEM-0074209220`). Strip whitespace,
    punctuation and case so equivalent numbers compare equal."""
    if not s:
        return ""
    import re as _re
    return _re.sub(r"[\s\-_./,]+", "", str(s)).upper()


def _find_cheapest_vendor_match(part: dict, vendor_comparison: dict | None) -> dict | None:
    """Return the cheapest in-stock vendor quote that matches `part`, or None.

    Matching rules (most specific first):
      1. Vendor quote's `oem_number` equals ALLDATA part's `oem_number`
         (after normalisation). This is the safest match — the shop is
         pricing the same OEM SKU across multiple suppliers.
      2. The OEM hint the worker passed to `gather_quotes` (stored as
         the vendor-comparison group key) equals the part's OEM number.
         This catches the common case where the worker only asked vendors
         about the primary OEM but ALLDATA listed several interchangeable
         numbers for the same part type.

    Preferred quote within a match set: in-stock beats out-of-stock; among
    quotes of equal stock status, the lowest price wins.
    """
    if not vendor_comparison:
        return None
    target_oem = _normalize_oem(part.get("oem_number"))
    best = None
    for requested_part, group in (vendor_comparison or {}).items():
        if not isinstance(group, dict):
            continue
        group_key = _normalize_oem(requested_part)
        for q in (group.get("all") or []):
            if not q or not q.get("found"):
                continue
            try:
                price = float(q.get("price"))
            except (TypeError, ValueError):
                continue
            q_oem = _normalize_oem(q.get("oem_number"))
            # Allow either side-of-match: vendor's OEM matches our part, OR
            # the group's request key matches our part (the gather_quotes
            # caller's hint, which is by definition this part's OEM).
            if not (target_oem and (q_oem == target_oem or group_key == target_oem)):
                continue
            if best is None:
                best = (q, price); continue
            best_quote, best_price = best
            # Stock preference > price preference (a $5 OOS row beats a $5
            # in-stock row would be wrong — the shop can't order OOS today).
            cur_in = bool(q.get("in_stock"))
            best_in = bool(best_quote.get("in_stock"))
            if cur_in and not best_in:
                best = (q, price)
            elif cur_in == best_in and price < best_price:
                best = (q, price)
    return best[0] if best else None


def _build_result_payload(job: dict, vehicle, labor, meta, elapsed: float,
                          vendor_quotes: list | None = None,
                          vendor_comparison: dict | None = None) -> dict:
    """Shape the agent output to match the Backend's JobResult schema.

    Part-pricing policy: for each part ALLDATA found, look up the cheapest
    in-stock vendor quote with a matching OEM number and use that as the
    line cost. This makes the estimate's parts total reflect what the
    shop will actually pay rather than ALLDATA's MSRP-style list price,
    matching the "Using in Estimate: X from Vendor" claim VendorCompare
    shows in the UI. When no vendor match exists (no quotes, no matching
    OEM, or all out-of-stock without a price), the ALLDATA list cost is
    kept as a safe fallback so totals never go missing.
    """
    labor_rate = float(job.get("laborRate") or 150.0)
    parts_markup_pct = float(job.get("partsMarkup") or 30.0)
    tax_rate = float(job.get("taxRate") or 0.0925)

    labor_lines = []
    labor_total = 0.0
    if labor:
        line_total = round(labor.hours * labor_rate, 2)
        labor_total += line_total
        labor_lines.append({
            "description": labor.operation,
            "hours": labor.hours,
            "rate": labor_rate,
            "total": line_total,
            "source": "ALLDATA",
            "skill": (labor.vehicle_match or {}).get("skill"),
        })

    parts_lines = []
    parts_total = 0.0
    for p in (meta.get("parts") or []):
        alldata_cost = float(p.get("price") or 0.0)
        vendor_match = _find_cheapest_vendor_match(p, vendor_comparison)

        if vendor_match is not None:
            try:
                vendor_price = float(vendor_match.get("price"))
            except (TypeError, ValueError):
                vendor_price = None
        else:
            vendor_price = None

        # Use the vendor price whenever we have a real quote — it represents
        # the shop's actual cost. ALLDATA's "price" is reference/MSRP and
        # over-states what the shop pays for aftermarket-equivalent parts.
        if vendor_price is not None:
            cost = vendor_price
            vendor_label = vendor_match.get("vendor") or "ALLDATA"
            brand = (vendor_match.get("brand") or "").strip()
            if brand:
                vendor_label = f"{vendor_label} · {brand}"
        else:
            cost = alldata_cost
            vendor_label = (p.get("vendor") or "ALLDATA").strip() or "ALLDATA"

        markup_dollars = round(cost * parts_markup_pct / 100.0, 2)
        qty = int(p.get("qty") or p.get("quantity") or 1)
        line_total = round((cost + markup_dollars) * qty, 2)
        parts_total += line_total

        line = {
            "description": p.get("name") or "",
            "partNumber": p.get("oem_number"),
            "quantity": qty,
            "cost": cost,
            "markup": parts_markup_pct,
            "total": line_total,
            "vendor": vendor_label,
        }
        # When we did substitute a vendor price, surface the savings vs the
        # ALLDATA list so the UI / advisor can see why this row is below
        # MSRP. Cheap to compute, doesn't bloat the payload when irrelevant.
        if vendor_price is not None and alldata_cost > 0 and vendor_price < alldata_cost:
            line["list_price"] = round(alldata_cost, 2)
            line["savings_vs_list"] = round(alldata_cost - vendor_price, 2)
        parts_lines.append(line)

    # If ALLDATA listed no OEM parts at all but vendors did return quotes
    # (typical of maintenance jobs: oil change, brake-fluid flush, tire
    # rotation), synthesise one part line per requested-part group from the
    # cheapest in-stock vendor quote. Without this step a routine
    # maintenance estimate ships with $0 parts even though the shop will
    # buy the oil filter / cabin filter / etc. from a vendor in stock today.
    if not parts_lines and vendor_comparison:
        for requested_part, group in (vendor_comparison or {}).items():
            if not isinstance(group, dict):
                continue
            best = group.get("best") or None
            if not best:
                continue
            try:
                cost = float(best.get("price"))
            except (TypeError, ValueError):
                continue
            if cost <= 0:
                continue
            vendor_label = best.get("vendor") or "Vendor"
            brand = (best.get("brand") or "").strip()
            if brand:
                vendor_label = f"{vendor_label} · {brand}"
            description = best.get("matched_part_name") or requested_part
            markup_dollars = round(cost * parts_markup_pct / 100.0, 2)
            qty = 1
            line_total = round((cost + markup_dollars) * qty, 2)
            parts_total += line_total
            parts_lines.append({
                "description": description,
                "partNumber": best.get("oem_number"),
                "quantity": qty,
                "cost": cost,
                "markup": parts_markup_pct,
                "total": line_total,
                "vendor": vendor_label,
            })

    subtotal = round(labor_total + parts_total, 2)
    tax_amount = round(subtotal * tax_rate, 2)
    grand_total = round(subtotal + tax_amount, 2)

    verification = meta.get("verification") or {}
    agent_run = meta.get("agent_run") or {}

    return {
        "vehicleInfo": {
            "year": vehicle.year,
            "make": vehicle.make,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "engine": vehicle.engine,
        },
        "laborItems": labor_lines,
        "partsItems": parts_lines,
        "breakdown": {
            "laborTotal": round(labor_total, 2),
            "partsTotal": round(parts_total, 2),
            "subtotal": subtotal,
            "taxAmount": tax_amount,
            "total": grand_total,
        },
        "section_path": meta.get("section_path"),
        "extraction_confidence": float(meta.get("extraction_confidence") or 0.0),
        "verification_match": bool(verification.get("match", False)),
        "verification_confidence": float(verification.get("confidence") or 0.0),
        "verification_reason": verification.get("reason"),
        "agent_steps": int(agent_run.get("steps_taken") or 0),
        "elapsed_sec": round(elapsed, 1),
        "vendorQuotes": vendor_quotes or [],
        "vendorComparison": vendor_comparison or {},
    }


async def _process_job(client: httpx.AsyncClient, hermes: HermesClient, job: dict) -> None:
    job_id = job["job_id"]
    vin = job["vin"]
    complaint = job["serviceRequest"]
    logger.info(f"[{job_id}] VIN={vin}  '{complaint[:80]}'")
    t0 = time.time()

    try:
        # 1. Hermes parse
        await _post_progress(client, job_id, "Parsing complaint with Hermes 3", 15)
        job_dict = hermes.parse_job_spec(complaint, vin)
        spec = JobSpec(**job_dict)

        # 2. NHTSA VIN decode
        await _post_progress(client, job_id, "Decoding VIN via NHTSA vPIC", 25)
        vehicle = await decode_vin(vin)
        logger.info(f"[{job_id}] decoded: {vehicle.year} {vehicle.make} {vehicle.model}")

        # 2b. Fail fast on an invalid / un-decodable VIN before spending an
        # expensive agent run. ALLDATA needs at least year + make + model.
        if not (vehicle.year and vehicle.make and vehicle.model):
            err = (
                f"VIN decoded incompletely: '{vehicle.year} {vehicle.make} {vehicle.model}'. "
                f"This VIN is likely invalid or not in the NHTSA database — please verify it."
            )
            logger.error(f"[{job_id}] {err}")
            await _post_failure(client, job_id, err)
            return

        # 3. Ensure the ALLDATA session is alive (transparent auto-relogin)
        from portals.auth import ensure_logged_in
        login_status = await ensure_logged_in("alldata")
        if not login_status.get("ok"):
            err = ("ALLDATA session is logged out and auto-relogin failed — "
                   "check ALLDATA credentials in .env or re-login via noVNC.")
            logger.error(f"[{job_id}] {err}")
            await _post_failure(client, job_id, err)
            return

        # 4. Reset Chrome to vehicle selector. If we can't land on the
        # selector, fail fast — running the vision agent against a login or
        # error page just burns 25 steps before reporting the same root cause.
        await _post_progress(client, job_id, f"Opening ALLDATA for {vehicle.year} {vehicle.make} {vehicle.model}", 35)
        reset_ok = await _reset_to_vehicle_selector()
        if not reset_ok:
            err = ("Could not reach the ALLDATA vehicle selector — page redirected "
                   "(session may have just dropped, or ALLDATA returned an error page). "
                   "Re-check ALLDATA login via noVNC.")
            logger.error(f"[{job_id}] {err}")
            await _post_failure(client, job_id, err)
            return

        # 4. Run the vision agent (hard timeout so a hang can't wedge the worker)
        await _post_progress(client, job_id, "Running ALLDATA vision agent (Gemini)", 50)
        try:
            labor, meta = await asyncio.wait_for(
                lookup_labor_time(spec, vehicle, max_steps=25), timeout=JOB_TIMEOUT
            )
        except asyncio.TimeoutError:
            err = f"Timed out after {JOB_TIMEOUT}s — ALLDATA agent did not finish (site slow or stuck)."
            logger.error(f"[{job_id}] {err}")
            await _post_failure(client, job_id, err)
            return

        if not labor:
            # Surface WHY: include the agent's last note, and flag the common
            # case of an expired ALLDATA login so the operator knows to act.
            last_note = ""
            try:
                hist = (meta or {}).get("history") or []
                if hist:
                    last_note = str(hist[-1].get("reason") or "")[:200]
            except Exception:
                pass
            lowered = last_note.lower()
            if any(k in lowered for k in ("log in", "login", "sign in", "session", "logged out")):
                err = ("ALLDATA session appears to have expired — please re-login via noVNC. "
                       f"Agent note: {last_note}")
            elif any(k in lowered for k in ("vehicle", "vin", "year", "make", "model")):
                err = ("Could not select the vehicle in ALLDATA (VIN not recognised by ALLDATA "
                       f"or selector changed). Agent note: {last_note}")
            else:
                err = f"ALLDATA agent did not extract a labor row. Agent note: {last_note or 'see screenshots for trace'}"
            logger.error(f"[{job_id}] {err}")
            await _post_failure(client, job_id, err)
            return

        # 4b. Vendor pricing.
        #
        # ALLDATA's "parts and labor" article often DOESN'T list OEM parts for
        # routine maintenance (oil change, brake-fluid flush, tire rotation),
        # only labor times — the parts are commodity items. The previous code
        # gated the entire vendor-pricing block on `alldata_parts` being
        # non-empty, so an oil-change estimate came back with $0 parts and
        # an empty Vendor Compare even though Worldpac/SSF would have happily
        # quoted an oil filter for the same vehicle.
        #
        # We now always attempt vendor pricing whenever there's a usable
        # part_type. When ALLDATA produced OEM parts we still derive the
        # primary `oem_hint` from them; when it didn't, `oem_hint` is None
        # and the vendor agents rely purely on the keyword path
        # (gather_quotes' variants chain auto-expands "Oil Change"-style
        # operations into the canonical catalog labels).
        vendor_quotes_dicts: list = []
        vendor_comparison: dict = {}
        try:
            from portals.vendors import gather_quotes, summarise
            alldata_parts = (meta.get("parts") or [])
            part_type = (labor.operation or "").strip() or (job.get("serviceRequest") or "")[:40]
            if part_type:
                if alldata_parts:
                    progress_msg = "Pricing ALLDATA OEM parts across vendors (Worldpac/SSF)"
                else:
                    progress_msg = (
                        "ALLDATA listed labor only — asking vendors for matching parts"
                    )
                await _post_progress(client, job_id, progress_msg, 75)

                oem_hint = None
                if alldata_parts:
                    # Aftermarket distributors are searched by VEHICLE + part
                    # type; keep the best OEM number as a cross-reference hint
                    # so the worker's vendor-match logic can substitute the
                    # cheaper vendor quote into the parts breakdown.
                    op_terms = [t for t in (labor.operation or "").lower().split() if t]
                    for p in alldata_parts:
                        if p.get("oem_number") and any(t in (p.get("name") or "").lower() for t in op_terms):
                            oem_hint = str(p["oem_number"]); break
                    if not oem_hint:
                        oem_hint = str(alldata_parts[0].get("oem_number") or "") or None

                complaint_text = (job.get("serviceRequest") or "").strip() or None
                vq = await gather_quotes(vehicle, part_type, oem_hint=oem_hint,
                                         complaint=complaint_text)
                vendor_quotes_dicts = [q.model_dump() for q in vq]
                vendor_comparison = summarise(vq)
                logger.info(f"[{job_id}] vendor quotes: {len(vendor_quotes_dicts)} "
                            f"across {len(vendor_comparison)} part(s)"
                            f"  (alldata_parts={len(alldata_parts)})")
        except Exception as e:
            logger.warning(f"[{job_id}] vendor pricing skipped: {e}")

        # 5. Build payload & post
        await _post_progress(client, job_id, "Verifying with Hermes + finalising", 90)
        elapsed = time.time() - t0
        result = _build_result_payload(job, vehicle, labor, meta, elapsed,
                                       vendor_quotes=vendor_quotes_dicts,
                                       vendor_comparison=vendor_comparison)

        await _post_result(client, job_id, result)
        logger.info(
            f"[{job_id}] DONE  '{labor.operation}' {labor.hours}h  "
            f"parts={len(result['partsItems'])}  total=${result['breakdown']['total']:.2f}  "
            f"{elapsed:.1f}s"
        )

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[{job_id}] EXCEPTION: {e}\n{tb}")
        await _post_failure(client, job_id, f"{type(e).__name__}: {str(e)[:300]}")


async def _claim_next_tekmetric(client: httpx.AsyncClient) -> Optional[dict]:
    """Try to claim a Tekmetric write-back job. Same shape as the auto-gen
    claim — returns None when the queue is empty so the main loop just
    falls through to the next polling tick."""
    try:
        r = await client.get(
            f"{BACKEND_URL}/api/v1/tekmetric/jobs/pending/next",
            params={"worker_id": WORKER_ID},
            headers=_headers(),
            timeout=20,
        )
        if r.status_code == 200 and r.text and r.text != "null":
            return r.json()
        if r.status_code in (200, 204):
            return None
    except Exception as e:
        logger.warning(f"tekmetric claim error: {e}")
    return None


async def _process_tekmetric_job(client: httpx.AsyncClient, job: dict) -> None:
    """Drive the Tekmetric vision agent for one push job."""
    from portals import tekmetric as tek_portal

    job_id = job.get("job_id")
    estimate = job.get("estimate") or {}
    customer = (estimate.get("customer") or {}).get("name", "—")
    veh = (estimate.get("vehicleInfo") or {}).get("vin", "—")
    logger.info(f"[{job_id}] Tekmetric push | customer={customer!r} VIN={veh}")

    async def _progress(msg: str, pct: int):
        try:
            await client.post(
                f"{BACKEND_URL}/api/v1/tekmetric/jobs/{job_id}/progress",
                headers=_headers(),
                json={"progress": msg, "progress_pct": pct},
                timeout=15,
            )
        except Exception as e:
            logger.warning(f"[{job_id}] tek progress post failed: {e}")

    async def _fail(err: str):
        try:
            await client.post(
                f"{BACKEND_URL}/api/v1/tekmetric/jobs/{job_id}/fail",
                headers=_headers(),
                json={"error": err},
                timeout=15,
            )
        except Exception as e:
            logger.warning(f"[{job_id}] tek fail post failed: {e}")

    await _progress("Opening Tekmetric in Chrome", 20)
    try:
        ok, result = await asyncio.wait_for(
            tek_portal.push_estimate(estimate), timeout=JOB_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await _fail(f"Tekmetric push timed out after {JOB_TIMEOUT}s")
        return
    except Exception as e:
        import traceback
        logger.error(f"[{job_id}] Tekmetric push EXCEPTION: {e}\n{traceback.format_exc()}")
        await _fail(f"{type(e).__name__}: {str(e)[:300]}")
        return

    if not ok:
        await _fail(result.get("error") or "Tekmetric agent did not produce an RO number")
        return

    try:
        payload = {
            "ok": True,
            "ro_number": str(result.get("ro_number") or ""),
            "ro_url": result.get("ro_url"),
            "customer_action": result.get("customer_action"),
            "vehicle_action": result.get("vehicle_action"),
            "labor_lines_added": result.get("labor_lines_added"),
            "parts_lines_added": result.get("parts_lines_added"),
            "note": result.get("note"),
        }
        await client.post(
            f"{BACKEND_URL}/api/v1/tekmetric/jobs/{job_id}/result",
            headers=_headers(),
            json=payload,
            timeout=20,
        )
        logger.info(f"[{job_id}] Tekmetric DONE  RO#{payload['ro_number']}")
    except Exception as e:
        logger.warning(f"[{job_id}] tek result post failed: {e}")


async def main_loop():
    logger.info(f"Estimaro Worker starting | worker_id={WORKER_ID} | backend={BACKEND_URL}")
    hermes = HermesClient()
    async with httpx.AsyncClient() as client:
        # Sanity ping
        try:
            r = await client.get(f"{BACKEND_URL}/health", timeout=10)
            logger.info(f"backend health: {r.status_code} {r.text[:80]}")
        except Exception as e:
            logger.warning(f"backend health check failed: {e}")

        # IMPORTANT: seed last_keepalive to NOW (not 0.0). Initialising to 0.0
        # made the `now - last_keepalive >= interval` check fire on the very
        # first idle tick after every restart, kicking off relogin_all() for
        # all five portals in rapid succession — that, combined with the fact
        # that each ensure_logged_in opens its own CDP connection, was
        # observed to cause `BrowserType.connect_over_cdp: Timeout 30000ms`
        # storms after deploys. With this seed the first keepalive fires
        # exactly one `keepalive_interval` after start, which matches the
        # intended cadence.
        last_keepalive = time.time()
        keepalive_interval = int(os.environ.get("SESSION_KEEPALIVE_SEC", "1800"))  # 30 min
        while True:
            # Priority order: drain the (cheap, short) Tekmetric push queue
            # before reaching for the next auto-generate run. A push needs
            # human-prompt-snappy response; an auto-gen run can wait its turn.
            tek_job = await _claim_next_tekmetric(client)
            if tek_job:
                await _process_tekmetric_job(client, tek_job)
                await asyncio.sleep(1)
                continue

            job = await _claim_next(client)
            if job:
                await _process_job(client, hermes, job)
                # Brief pause to let ALLDATA settle
                await asyncio.sleep(2)
            else:
                # Idle: opportunistically keep portal sessions warm. Safe here
                # because no job is running, so we never fight the agent for the
                # shared Chrome tabs.
                now = time.time()
                if now - last_keepalive >= keepalive_interval:
                    last_keepalive = now
                    try:
                        from portals.auth import relogin_all
                        results = await relogin_all()
                        relogged = [r["portal"] for r in results if r.get("action") == "relogin"]
                        failed = [r["portal"] for r in results if not r.get("ok")]
                        if relogged:
                            logger.info(f"[keepalive] re-logged in: {relogged}")
                        if failed:
                            logger.warning(f"[keepalive] login failed: {failed}")
                    except Exception as e:
                        logger.warning(f"[keepalive] error: {e}")
                await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        sys.exit(0)
