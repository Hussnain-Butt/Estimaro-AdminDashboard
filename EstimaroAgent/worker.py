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


async def _reset_to_vehicle_selector():
    """Force the live ALLDATA tab back to the vehicle selector before each job."""
    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus("https://my.alldata.com/repair/#/select-vehicle")
            try:
                await page.goto("https://my.alldata.com/repair/#/select-vehicle",
                                wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"reset navigation failed: {e}")
    except Exception as e:
        logger.warning(f"reset_to_vehicle_selector outer error: {e}")


def _build_result_payload(job: dict, vehicle, labor, meta, elapsed: float,
                          vendor_quotes: list | None = None,
                          vendor_comparison: dict | None = None) -> dict:
    """Shape the agent output to match the Backend's JobResult schema."""
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
        cost = float(p.get("price") or 0.0)
        markup_dollars = round(cost * parts_markup_pct / 100.0, 2)
        qty = int(p.get("qty") or p.get("quantity") or 1)
        line_total = round((cost + markup_dollars) * qty, 2)
        parts_total += line_total
        parts_lines.append({
            "description": p.get("name") or "",
            "partNumber": p.get("oem_number"),
            "quantity": qty,
            "cost": cost,
            "markup": parts_markup_pct,
            "total": line_total,
            "vendor": p.get("vendor") or "ALLDATA",
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

        # 4. Reset Chrome to vehicle selector
        await _post_progress(client, job_id, f"Opening ALLDATA for {vehicle.year} {vehicle.make} {vehicle.model}", 35)
        await _reset_to_vehicle_selector()

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

        # 4b. Vendor pricing — look up ALLDATA's OEM part numbers on the
        # distributor portals (Worldpac/SSF) for real buy price + availability.
        vendor_quotes_dicts: list = []
        vendor_comparison: dict = {}
        try:
            from portals.vendors import gather_quotes, summarise
            alldata_parts = (meta.get("parts") or [])
            if alldata_parts:
                await _post_progress(client, job_id, "Pricing parts across vendors (Worldpac/SSF)", 75)
                # Aftermarket distributors are searched by VEHICLE + part type, so
                # derive the part type from the labor operation, and keep the best
                # OEM number as a cross-reference hint.
                part_type = (labor.operation or "").strip() or (job.get("serviceRequest") or "")[:40]
                op_terms = [t for t in (labor.operation or "").lower().split() if t]
                oem_hint = None
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
                            f"across {len(vendor_comparison)} part(s)")
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

        last_keepalive = 0.0
        keepalive_interval = int(os.environ.get("SESSION_KEEPALIVE_SEC", "1800"))  # 30 min
        while True:
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
