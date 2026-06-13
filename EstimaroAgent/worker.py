"""Estimaro Agent Worker.

Polls the Railway backend for queued auto-generate jobs, runs the full
Hermes -> NHTSA -> ALLDATA agent pipeline, posts result back.

Run as a systemd service `estimaro-agent.service`.
"""
import asyncio
import base64
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
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
    navigation. Returns False if, after a one-shot relogin recovery attempt,
    ALLDATA still redirects somewhere else (subscription lapsed, account
    locked, login broken) — the caller can use this to fail fast instead of
    running the agent against the wrong starting state.

    Recovery rationale: the keepalive runs every 30 min, but a job that
    arrives 29 min into that window can race the session expiry. If the
    nav lands on bare /alldata.com/ or the login form, calling
    ensure_logged_in restores the session in-place; we then retry the
    same navigation ONCE before giving up. This fixes the silent
    'session dropped between keepalive and job arrival' failure mode.
    """
    target = "https://my.alldata.com/repair/#/select-vehicle"

    async def _try_once() -> tuple[bool, str]:
        try:
            async with ChromeDebugBrowser() as browser:
                page = await browser.open_or_focus(target)
                try:
                    await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
                except Exception as e:
                    return False, f"nav_failed: {e}"
                if "select-vehicle" not in page.url:
                    return False, f"unexpected_url: {page.url}"
                return True, "ok"
        except Exception as e:
            return False, f"outer: {e}"

    ok, why = await _try_once()
    if ok:
        return True

    # First attempt failed. If we landed on a non-selector URL, the most
    # likely cause is a dropped session. Try a relogin and retry once.
    logger.warning(f"reset attempt 1 failed ({why}) — trying alldata relogin recovery")
    try:
        from portals.auth import ensure_logged_in
        status = await ensure_logged_in("alldata")
        if not status.get("ok"):
            logger.warning(
                f"reset: relogin recovery failed "
                f"(action={status.get('action')!r}, error={status.get('error')!r}) — "
                f"giving up"
            )
            return False
        logger.info(f"reset: relogin recovery succeeded ({status.get('action')!r}) — retrying nav")
    except Exception as e:
        logger.warning(f"reset: relogin recovery raised {e!r} — giving up")
        return False

    ok2, why2 = await _try_once()
    if not ok2:
        logger.warning(f"reset attempt 2 (post-relogin) also failed: {why2}")
    return ok2


def _normalize_oem(s) -> str:
    """OEM numbers come back from each portal with different formatting
    (`0074209220` vs `007 420 92 20` vs `OEM-0074209220`). Strip whitespace,
    punctuation and case so equivalent numbers compare equal."""
    if not s:
        return ""
    import re as _re
    return _re.sub(r"[\s\-_./,]+", "", str(s)).upper()


def _compute_consensus(vendor_comparison: dict | None) -> dict:
    """Cross-source consensus for the proposal's Layer 5.

    For every requested-part group we summarise the spread of vendor prices —
    how many vendors responded, how many returned an actual price, the
    median/min/max, and which (if any) quotes are statistical outliers vs the
    median. This is the signal Cross-Source Consensus is meant to surface:
    when 3 vendors agree within 10% the buy price is trustworthy; when 1
    vendor sits at 2× the others it's almost certainly a mismatched SKU and
    should be flagged for the advisor — not silently treated as cheapest.

    Output shape per part key:
        {
          "vendors_total":         <int>,   # rows returned for this part
          "vendors_with_price":    <int>,   # rows that carried a real price
          "vendors_in_stock":      <int>,   # priced + in_stock
          "median_price":          <float | null>,
          "min_price":             <float | null>,
          "max_price":             <float | null>,
          "spread_pct":            <float | null>,  # (max-min)/median, 0..inf
          "outliers": [{"vendor": "X", "price": Y, "delta_pct": +Z}],
          "oem_agreement":         <float 0..1>,    # frac of priced rows whose
                                                    # OEM matched the requested key
        }

    Outlier rule: a priced row whose price is >50% above OR below the median
    is flagged. With only 1 priced row there is no median and no outliers.
    """
    out: dict[str, dict] = {}
    for requested, group in (vendor_comparison or {}).items():
        if not isinstance(group, dict):
            continue
        rows = [q for q in (group.get("all") or []) if isinstance(q, dict)]
        priced = []
        for q in rows:
            try:
                p = float(q.get("price"))
            except (TypeError, ValueError):
                continue
            if p > 0:
                priced.append((q, p))
        if not rows:
            continue
        in_stock = sum(1 for q, _ in priced if q.get("in_stock"))
        target_key = _normalize_oem(requested)
        if priced:
            prices = sorted(p for _, p in priced)
            n = len(prices)
            mid = n // 2
            median = (prices[mid] if n % 2 else (prices[mid - 1] + prices[mid]) / 2.0)
            mn, mx = prices[0], prices[-1]
            spread = ((mx - mn) / median) if median > 0 else None
            outliers = []
            if n >= 2 and median > 0:
                for q, p in priced:
                    delta = (p - median) / median
                    if abs(delta) > 0.5:
                        outliers.append({
                            "vendor": q.get("vendor"),
                            "brand": q.get("brand"),
                            "price": round(p, 2),
                            "delta_pct": round(delta * 100, 1),
                        })
            oem_agree = 0
            if target_key:
                for q, _ in priced:
                    if _normalize_oem(q.get("oem_number")) == target_key:
                        oem_agree += 1
            oem_agreement = (oem_agree / n) if n else 0.0
            out[requested] = {
                "vendors_total": len(rows),
                "vendors_with_price": n,
                "vendors_in_stock": in_stock,
                "median_price": round(median, 2),
                "min_price": round(mn, 2),
                "max_price": round(mx, 2),
                "spread_pct": (round(spread * 100, 1) if spread is not None else None),
                "outliers": outliers,
                "oem_agreement": round(oem_agreement, 2),
            }
        else:
            out[requested] = {
                "vendors_total": len(rows),
                "vendors_with_price": 0,
                "vendors_in_stock": 0,
                "median_price": None,
                "min_price": None,
                "max_price": None,
                "spread_pct": None,
                "outliers": [],
                "oem_agreement": 0.0,
            }
    return out


def _compute_overall_confidence(
    extraction_conf: float,
    verification_conf: float,
    consensus: dict | None,
) -> dict:
    """Layer 6: aggregate confidence + tier routing for the FE badge.

    Inputs:
      * extraction_conf — Gemini's self-rated confidence on the labor row
      * verification_conf — Hermes verifier's match confidence vs JobSpec
      * consensus — per-part output of _compute_consensus

    Sourcing score: 1.0 when ≥2 vendors returned a price AND no outliers,
    0.7 when ≥2 priced but with outliers, 0.5 when only 1 priced (the
    single-source downgrade the proposal calls out), 0.3 when 0 priced.

    Aggregate: weighted average extraction (0.35) + verification (0.35) +
    sourcing (0.30). Tier thresholds match the proposal's gating rule
    (≥0.90 auto, 0.70-0.89 advisor, <0.70 manual).
    """
    ex = max(0.0, min(1.0, float(extraction_conf or 0.0)))
    vf = max(0.0, min(1.0, float(verification_conf or 0.0)))

    # Sourcing — derived from consensus across ALL part groups.
    sourcing = 0.3
    sourcing_note = "no_vendors_returned"
    if consensus:
        priced_groups = [c for c in consensus.values()
                         if (c.get("vendors_with_price") or 0) >= 1]
        if priced_groups:
            min_priced = min(c.get("vendors_with_price") or 0 for c in priced_groups)
            any_outliers = any(c.get("outliers") for c in priced_groups)
            if min_priced >= 2 and not any_outliers:
                sourcing, sourcing_note = 1.0, "multi_source_agreement"
            elif min_priced >= 2 and any_outliers:
                sourcing, sourcing_note = 0.7, "multi_source_with_outliers"
            else:
                sourcing, sourcing_note = 0.5, "single_source"

    score = round(0.35 * ex + 0.35 * vf + 0.30 * sourcing, 3)
    if score >= 0.90:
        tier = "auto"
    elif score >= 0.70:
        tier = "advisor_review"
    else:
        tier = "manual_review"

    return {
        "score": score,
        "tier": tier,
        "breakdown": {
            "extraction": round(ex, 3),
            "verification": round(vf, 3),
            "sourcing": round(sourcing, 3),
            "sourcing_note": sourcing_note,
        },
    }


def _load_screenshot_b64(path: Optional[str], max_bytes: int = 600_000) -> Optional[str]:
    """Read an extraction screenshot from disk and return a data-URL string.

    Returns None when:
      * path is empty / falsy
      * the file doesn't exist or isn't readable
      * the encoded payload would exceed `max_bytes` (avoid 2 MB PNGs
        bloating every job result — anything that big is likely a
        scaling-error screenshot anyway)

    Embedded as a data URL so the FE can drop it into an <img src=...>
    without a second round-trip; the proposal's "explainable estimate
    with a screenshot trail" is otherwise blocked on either an S3
    upload pipeline or a backend proxy, neither of which is in scope
    for this PR.
    """
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        data = p.read_bytes()
        if len(data) > max_bytes:
            logger.info(
                f"screenshot {p.name} too large ({len(data)} bytes) — "
                f"skipping embed"
            )
            return None
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        logger.warning(f"screenshot load failed for {path!r}: {e}")
        return None


async def _get_recalls(make: str | None, model: str | None,
                       year: int | None) -> list[dict]:
    """Fetch active NHTSA recalls for the decoded vehicle.

    NHTSA Safety API is free and uncreedled. Returns a compact list of
    {campaign_number, component, summary, remedy} dicts the FE can render
    as a banner. Quiet on any error — recalls are auxiliary; a NHTSA
    outage must never block the estimate.
    """
    if not (make and model and year):
        return []
    url = "https://api.nhtsa.gov/recalls/recallsByVehicle"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params={
                "make": make, "model": model, "modelYear": str(year),
            })
        if r.status_code != 200:
            return []
        data = r.json()
        results = data.get("results") or []
        out = []
        # Cap at 8 — typical vehicles have 1-3, but Volvo XC70s of this era
        # can have 10+. Truncating keeps the payload reasonable and the FE
        # banner readable; full list is one click away on NHTSA itself.
        for rec in results[:8]:
            out.append({
                "campaign_number": rec.get("NHTSACampaignNumber"),
                "component": rec.get("Component"),
                "summary": (rec.get("Summary") or "")[:400],
                "remedy": (rec.get("Remedy") or "")[:300],
                "report_received_date": rec.get("ReportReceivedDate"),
            })
        return out
    except Exception as e:
        logger.warning(f"recalls fetch failed: {e}")
        return []


# Static job -> recommended add-ons map. The proposal's "Add-on detection"
# pipeline step is meant to be a job-classifier output; until that classifier
# exists, this static map covers the common American shop add-ons that the
# advisor would otherwise have to remember manually. Keys are matched against
# job.system / job.subsystem / job.keywords case-insensitively.
_ADDON_MAP = {
    "brake": [
        {"name": "Pad clip / hardware kit", "kind": "part",
         "reason": "Recommended with every pad replacement; clips wear and squeal"},
        {"name": "Rotor measurement / inspection", "kind": "inspection",
         "reason": "Confirm rotors are within spec before reusing"},
        {"name": "Brake fluid flush", "kind": "labor", "hours": 0.5,
         "reason": "Industry standard every 2 years or with brake service"},
    ],
    "oil": [
        {"name": "Oil filter", "kind": "part",
         "reason": "Always replaced with engine oil"},
        {"name": "Drain plug gasket / crush washer", "kind": "part",
         "reason": "Single-use on most modern engines"},
        {"name": "Multi-point inspection", "kind": "inspection",
         "reason": "Standard at every service interval"},
    ],
    "transmission": [
        {"name": "Transmission filter", "kind": "part",
         "reason": "Replaced with every fluid service when accessible"},
        {"name": "Pan gasket", "kind": "part",
         "reason": "Single-use on drop-pan transmissions"},
    ],
    "suspension": [
        {"name": "Alignment", "kind": "labor", "hours": 1.0,
         "reason": "Required after suspension component replacement"},
    ],
    "ignition": [
        {"name": "Spark plug boots / coil-on-plug check", "kind": "inspection",
         "reason": "Common failure point at plug-service intervals"},
    ],
    "cooling": [
        {"name": "Coolant flush", "kind": "labor", "hours": 0.5,
         "reason": "Replace fluid when system was opened"},
        {"name": "Pressure test", "kind": "inspection",
         "reason": "Verify no leaks after thermostat / radiator service"},
    ],
}


def _suggest_addons(job: JobSpec) -> list[dict]:
    """Look up recommended add-ons for the parsed JobSpec.

    Match priority: system → subsystem → keywords. The first key that hits
    wins; we don't merge across categories so a brake-job doesn't end up
    suggesting both pad clips AND oil filters when the symptom is brake-
    only. Empty list when no key matches — keeps the FE panel hidden
    instead of showing irrelevant cards.
    """
    pools = [(job.system or ""), (job.subsystem or "")]
    pools.extend(job.keywords or [])
    for token in pools:
        t = (token or "").lower()
        for key, addons in _ADDON_MAP.items():
            if key in t:
                return [dict(a) for a in addons]
    return []


def _dedup_parts(parts: list[dict]) -> list[dict]:
    """Collapse part variants that share an OEM number into a single line.

    ALLDATA sometimes lists the same physical part twice on a Parts-and-Labor
    page with different wheel-size / option qualifiers — e.g. "Front Pads
    (15\" Wheels)" and "Front Pads (16\" Wheels)" both with OEM 8634921. The
    physical pad is the same; only the vehicle's rim size determines which
    label applies. Adding both to the estimate double-bills the customer.

    Strategy: group by normalised OEM number (falls back to normalised name
    for parts without an OEM). Keep the FIRST occurrence as canonical, and
    record the other variants' display names on `applies_to_variants` so the
    UI can disclose that the same SKU covers multiple options.
    """
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for p in parts or []:
        key = _normalize_oem(p.get("oem_number")) or (
            "name:" + (p.get("name") or "").strip().lower()
        )
        if not key:
            out.append(p)
            continue
        if key in seen:
            # Merge variant label into the canonical row; do not bill twice.
            variant = (p.get("name") or "").strip()
            if variant and variant not in seen[key].setdefault("applies_to_variants", []):
                seen[key]["applies_to_variants"].append(variant)
            continue
        # Seed variants with this row's own name so the UI can render a
        # uniform "applies to" list even when there's only one entry.
        own = (p.get("name") or "").strip()
        p = {**p, "applies_to_variants": [own] if own else []}
        seen[key] = p
        out.append(p)
    # If a canonical entry ended up with only its own name in variants, drop
    # the field so the UI doesn't show a redundant single-item "applies to".
    for p in out:
        v = p.get("applies_to_variants")
        if isinstance(v, list) and len(v) <= 1:
            p.pop("applies_to_variants", None)
    return out


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


_AXLE_QUALIFIERS = {"front", "rear", "left", "right", "upper", "lower"}


def _partition_parts_by_skeleton(parts: list[dict],
                                 skeleton: dict) -> tuple[list[dict], list[dict]]:
    """Split ALLDATA-extracted parts into (billed, conditional) per the service
    skeleton — Sergio's SOP for the classified service type.

    ROOT CAUSE this fixes: ALLDATA's parts-and-labor article lists EVERY
    related/conditional component (calipers, flex hoses, backing plates, the
    other axle's pads). Billing them all inflated a $1,000 front-brake job to
    $2,165 on the FIRST build of every new VIN, which the advisor then had to
    strip by hand each time. The skeleton already encodes what the service
    actually includes — so bill only parts matching a skeleton component and
    surface the rest as suggested add-ons the advisor can opt into.

    Matching: each component's display_name/alldata_keywords/vendor_search_terms
    with axle qualifiers stripped, substring-matched against the part name.
    A part naming the OPPOSITE axle is always conditional. If nothing matches
    (unusual article wording), all parts stay billed — never ship an empty
    estimate because the SOP vocabulary missed.
    """
    stype = (skeleton.get("service_type") or "").lower()
    opposite = "rear" if "front" in stype else ("front" if "rear" in stype else None)

    phrases: list[str] = []
    for c in skeleton.get("components", []):
        cands = ([c.get("display_name", "")] +
                 list(c.get("alldata_keywords") or []) +
                 list(c.get("vendor_search_terms") or []))
        for t in cands:
            words = [w for w in re.split(r"[^a-z0-9]+", (t or "").lower())
                     if w and w not in _AXLE_QUALIFIERS]
            ph = " ".join(words).strip()
            if len(ph) > 2:
                phrases.append(ph)

    billed: list[dict] = []
    conditional: list[dict] = []
    for p in parts:
        en = (p.get("name") or "").lower()
        en_words = set(re.split(r"[^a-z0-9]+", en))
        if opposite and opposite in en_words:
            conditional.append(p)
            continue
        if any(ph in en for ph in phrases):
            billed.append(p)
        else:
            conditional.append(p)
    if not billed:
        return parts, []
    return billed, conditional


def _build_result_payload(job: dict, vehicle, labor, meta, elapsed: float,
                          vendor_quotes: list | None = None,
                          vendor_comparison: dict | None = None,
                          recalls: list | None = None,
                          suggested_addons: list | None = None,
                          service_skeleton: dict | None = None) -> dict:
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

    # Pricing matrices — mirror the shop's Tekmetric Parts/Labor matrices so the
    # estimate lands on the number their own software would bill (cost-bracket
    # parts markup + hours-tiered labor markup) instead of a flat placeholder.
    # On by default; a job can opt back to the legacy flat behaviour with
    # pricingMatrix=False (then partsMarkup% for parts, no labor markup).
    from services.pricing_matrix import (
        parts_markup_pct_for_cost, labor_multiplier_for_hours)
    use_matrix = job.get("pricingMatrix", True) is not False

    def _part_markup_pct(cost: float, no_markup: bool = False) -> float:
        if no_markup:
            return 0.0
        return parts_markup_pct_for_cost(cost) if use_matrix else parts_markup_pct

    def _labor_line(hours, rate: float) -> tuple[float, float, float]:
        """(base = hours×rate, multiplier, marked-up line total)."""
        base = round((hours or 0.0) * rate, 2)
        mult = labor_multiplier_for_hours(hours) if use_matrix else 1.0
        return base, mult, round(base * mult, 2)

    labor_lines = []
    labor_total = 0.0
    if labor:
        base_amount, labor_mult, line_total = _labor_line(labor.hours, labor_rate)
        labor_total += line_total
        # Embed the extraction-time screenshot as a data URL so the FE can
        # render a "View source" panel without a second round-trip. The
        # loader returns None on any failure (file missing, too big) and
        # the FE hides the panel in that case, so this never blocks the
        # estimate even when the screenshot disk is full.
        # Task #15 — determinism signal piped through so the FE can show
        # whether this labor row is the canonical pick for the service
        # type (matched_preferred / matched_fallback / off_script).
        det = (meta or {}).get("determinism") or {}
        labor_lines.append({
            "description": labor.operation,
            "hours": labor.hours,
            "rate": labor_rate,
            "total": line_total,
            "baseAmount": base_amount,
            "laborMultiplier": labor_mult,
            "laborMarkupPct": round((labor_mult - 1.0) * 100.0, 2),
            "source": "ALLDATA",
            "skill": (labor.vehicle_match or {}).get("skill"),
            "extractionScreenshot": _load_screenshot_b64(labor.screenshot_path),
            "determinism_status": det.get("status"),
            "determinism_rank": det.get("rank"),
            "determinism_preferred": det.get("preferred"),
        })

    parts_lines = []
    parts_total = 0.0
    # Dedup BEFORE pricing so the same OEM doesn't get billed twice when
    # ALLDATA listed it under multiple wheel-size / option labels.
    deduped_parts = _dedup_parts(meta.get("parts") or [])
    # SOP gate — bill only the parts the service skeleton declares for this
    # service type; everything else (ALLDATA's conditional rows: calipers,
    # flex hoses, the other axle) moves to suggested add-ons below.
    conditional_parts: list[dict] = []
    if service_skeleton:
        deduped_parts, conditional_parts = _partition_parts_by_skeleton(
            deduped_parts, service_skeleton)
        if conditional_parts:
            logger.info(
                f"[payload] SOP gate ({service_skeleton.get('service_type')}): "
                f"billing {len(deduped_parts)} part(s), moved "
                f"{len(conditional_parts)} conditional to suggested add-ons: "
                + ", ".join((p.get('name') or '?')[:30] for p in conditional_parts[:6]))
    for p in deduped_parts:
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

        markup_pct = _part_markup_pct(cost)
        markup_dollars = round(cost * markup_pct / 100.0, 2)
        qty = int(p.get("qty") or p.get("quantity") or 1)
        line_total = round((cost + markup_dollars) * qty, 2)
        parts_total += line_total

        line = {
            "description": p.get("name") or "",
            "partNumber": p.get("oem_number"),
            "quantity": qty,
            "cost": cost,
            "markup": markup_pct,
            "total": line_total,
            "vendor": vendor_label,
        }
        # Vendor SKU: the vendor's own part number (often DIFFERENT from the
        # OEM number ALLDATA listed — e.g. ALLDATA 8634921 vs SSF 573003J).
        # Exposing both lets the advisor cross-check what the vendor will
        # actually ship; without this the UI showed only one of the two and
        # the advisor couldn't tell which catalogue the number was from.
        if vendor_match is not None:
            vendor_sku = vendor_match.get("oem_number") or vendor_match.get("part_number")
            if vendor_sku and _normalize_oem(vendor_sku) != _normalize_oem(p.get("oem_number")):
                line["vendorSku"] = str(vendor_sku)
        # Carry merged variant labels through so the UI can disclose
        # "Also fits: 16\" wheels" instead of silently swallowing the dup.
        if p.get("applies_to_variants"):
            line["appliesToVariants"] = list(p["applies_to_variants"])
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
            markup_pct = _part_markup_pct(cost)
            markup_dollars = round(cost * markup_pct / 100.0, 2)
            qty = 1
            line_total = round((cost + markup_dollars) * qty, 2)
            parts_total += line_total
            parts_lines.append({
                "description": description,
                "partNumber": best.get("oem_number"),
                "quantity": qty,
                "cost": cost,
                "markup": markup_pct,
                "total": line_total,
                "vendor": vendor_label,
            })

    # Task #14 — auto-add skeleton addons (cleaning kit, multi-point
    # inspection, alignment labor) for service types that require them.
    # Sergio June 6: "we add a cleaning kit of like 35 bucks" for brake
    # services. The skeleton (task #12) declares these addons; this
    # block injects them as actual line items so they (a) contribute
    # to the estimate total and (b) show up in PartsStep/LaborStep
    # with an "auto-added" badge instead of just sitting on the
    # coverage panel as informational.
    if service_skeleton and isinstance(service_skeleton.get("addons"), list):
        for addon in service_skeleton["addons"]:
            if not isinstance(addon, dict):
                continue
            kind = (addon.get("kind") or "").lower()
            default_cost = addon.get("default_cost")
            no_markup = bool(addon.get("no_markup"))
            qty = int(addon.get("default_qty") or 1)
            display_name = addon.get("display_name") or addon.get("key") or "Add-on"
            reason = addon.get("reason") or "Auto-added per service type"

            if kind in ("supply", "inspection"):
                # Inspections are usually $0 (free with service); supplies
                # have a default cost (cleaning kit = $35).
                try:
                    cost = float(default_cost) if default_cost is not None else 0.0
                except (TypeError, ValueError):
                    cost = 0.0
                markup_pct = _part_markup_pct(cost, no_markup=no_markup)
                markup_dollars = round(cost * markup_pct / 100.0, 2)
                line_total = round((cost + markup_dollars) * qty, 2)
                parts_total += line_total
                parts_lines.append({
                    "description": display_name,
                    "partNumber": None,
                    "vendorSku": None,
                    "quantity": qty,
                    "cost": cost,
                    "markup": markup_pct,
                    "total": line_total,
                    "vendor": "Shop supplies" if kind == "supply" else "Shop service",
                    # Flags so FE can render an "Auto-added per service type"
                    # badge — operator knows the line wasn't from ALLDATA
                    # extraction or vendor quotes.
                    "auto_added": True,
                    "auto_added_kind": kind,
                    "auto_added_reason": reason,
                })
            elif kind == "labor":
                # Labor add-ons (e.g. Wheel Alignment for suspension) go
                # in labor_lines, not parts_lines.
                hours = float(addon.get("hours") or addon.get("default_qty") or 1.0)
                base_amount, labor_mult, line_total = _labor_line(hours, labor_rate)
                labor_total += line_total
                labor_lines.append({
                    "description": display_name,
                    "hours": hours,
                    "rate": labor_rate,
                    "total": line_total,
                    "baseAmount": base_amount,
                    "laborMultiplier": labor_mult,
                    "laborMarkupPct": round((labor_mult - 1.0) * 100.0, 2),
                    "source": "Skeleton (auto-added)",
                    "skill": None,
                    "extractionScreenshot": None,
                    "auto_added": True,
                    "auto_added_reason": reason,
                })

    # Surface SOP-gated conditional parts as opt-in suggestions (with their
    # ALLDATA reference price) instead of silently billing or dropping them.
    if conditional_parts:
        suggested_addons = list(suggested_addons or [])
        sop_name = (service_skeleton or {}).get("display_name") or "this service"
        for p in conditional_parts:
            suggested_addons.append({
                "name": p.get("name") or "",
                "kind": "conditional_part",
                "reason": (f"Listed by ALLDATA for this job but not part of the "
                           f"standard {sop_name} — add only if inspection shows "
                           f"it's needed"),
                "cost": p.get("price"),
                "oem_number": p.get("oem_number"),
            })

    subtotal = round(labor_total + parts_total, 2)
    tax_amount = round(subtotal * tax_rate, 2)
    grand_total = round(subtotal + tax_amount, 2)

    # Flat-fee services (oil change, brakes, plugs, trans fluid) are sold at a
    # near-fixed price per vehicle class, not a parts+labor buildup. When the
    # skeleton flags flat_fee and the corpus has enough comparable jobs, the
    # shop's MEDIAN past charge becomes the headline price (the itemized buildup
    # stays below as reference) — replacing a possibly-wrong live total with the
    # number the shop actually charges. Falls through silently when too sparse.
    flat_fee = None
    if service_skeleton and service_skeleton.get("flat_fee"):
        try:
            from services.historical_corpus import service_flat_fee
            ff = service_flat_fee(service_skeleton.get("service_type"),
                                  vehicle.year, vehicle.make, vehicle.model)
        except Exception as e:
            logger.warning(f"[payload] flat-fee lookup failed: {e}")
            ff = None
        if ff:
            fee_sub = ff["median"]
            fee_tax = round(fee_sub * tax_rate, 2)
            flat_fee = {
                "applied": True,
                "subtotal": fee_sub,
                "taxAmount": fee_tax,
                "total": round(fee_sub + fee_tax, 2),
                "low": ff["low"], "high": ff["high"], "n": ff["n"],
                "basis": ff.get("basis"),
                # The itemized buildup, kept for the advisor to compare against.
                "computedSubtotal": subtotal,
                "computedTotal": grand_total,
            }
            logger.info(
                f"[payload] flat fee for {service_skeleton.get('service_type')}: "
                f"${fee_sub} (median of {ff['n']} {ff.get('basis')} jobs) — "
                f"headline replaces computed ${grand_total}")

    verification = meta.get("verification") or {}
    agent_run = meta.get("agent_run") or {}

    # ALLDATA's banner often shows a more specific trim/sub-model than NHTSA
    # decoded (NHTSA: "2002 VOLVO V70"; ALLDATA banner: "2002 Volvo XC70
    # L5-2.4L Turbo"). Same platform, different label. Surface BOTH so the
    # advisor can confirm the labor row came from the right catalogue row
    # — and so the customer-facing estimate doesn't quietly mislabel the car.
    alldata_matched_vehicle = None
    try:
        if labor and labor.vehicle_match:
            reported = (labor.vehicle_match or {}).get("reported")
            if reported and isinstance(reported, str):
                alldata_matched_vehicle = reported.strip() or None
    except Exception:
        pass

    # Layer 5 + Layer 6: cross-source consensus + aggregate confidence with
    # tier routing. Both derived from data already in this payload, so the
    # FE doesn't have to recompute (and can't drift from the gating policy).
    consensus = _compute_consensus(vendor_comparison)
    confidence_summary = _compute_overall_confidence(
        extraction_conf=float(meta.get("extraction_confidence") or 0.0),
        verification_conf=float(verification.get("confidence") or 0.0),
        consensus=consensus,
    )

    return {
        "vehicleInfo": {
            "year": vehicle.year,
            "make": vehicle.make,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "engine": vehicle.engine,
        },
        "alldataMatchedVehicle": alldata_matched_vehicle,
        "laborItems": labor_lines,
        "partsItems": parts_lines,
        "breakdown": {
            "laborTotal": round(labor_total, 2),
            "partsTotal": round(parts_total, 2),
            "subtotal": subtotal,
            "taxAmount": tax_amount,
            "total": grand_total,
        },
        # Flat-fee headline for flat-fee services — None on variable-priced jobs.
        "flatFee": flat_fee,
        "section_path": meta.get("section_path"),
        "extraction_confidence": float(meta.get("extraction_confidence") or 0.0),
        "verification_match": bool(verification.get("match", False)),
        "verification_confidence": float(verification.get("confidence") or 0.0),
        "verification_reason": verification.get("reason"),
        "agent_steps": int(agent_run.get("steps_taken") or 0),
        "elapsed_sec": round(elapsed, 1),
        "vendorQuotes": vendor_quotes or [],
        "vendorComparison": vendor_comparison or {},
        # Layer 5 / Layer 6 — the FE renders these directly; do not let the
        # FE rebuild from raw vendorComparison or it will drift from the
        # gating thresholds we use to decide auto vs advisor vs manual.
        "consensus": consensus,
        "confidence": confidence_summary,
        # Aux data — NHTSA recalls active for the vehicle, and the
        # job-classifier's recommended add-ons (pad clips, oil filter, ...)
        # Both informational; the FE renders banners/panels but does not
        # auto-add to the estimate.
        "recalls": list(recalls or []),
        "suggestedAddOns": list(suggested_addons or []),
        # Task #12 — service-type skeleton + coverage report. Tells the FE
        # which components THIS service type is EXPECTED to have, and
        # whether the ALLDATA extraction found each one. The
        # `coverage_pct` is the headline number an advisor watches: 100%
        # means the estimate carries every component the skeleton asked
        # for; lower means line items are missing and the advisor needs
        # to add them manually.
        # Task #13 — Repair Procedure scan items piped in as a second
        # confirmation source so a component the procedure explicitly
        # tells the tech to "renew" is marked confirmed even when the
        # Parts table didn't list it (the BMW carrier-bolt + Volvo
        # crush-washer cases Sergio walked through).
        "serviceSkeleton": _build_skeleton_coverage(
            service_skeleton, parts_lines,
            repair_procedure=(meta or {}).get("repair_procedure"),
        ),
        "repairProcedure": (meta or {}).get("repair_procedure") or {"items": [], "scan_status": "not_attempted"},
    }


def _clean_hist_labor_desc(desc: str) -> str:
    """Strip the technician credit Tekmetric appends to a labor description
    (e.g. 'REPLACED COOLANT (Tech: CHRISTIAN GARCIA)') — it's the tech who did
    the work, not part of the customer-facing service description. Handles a
    truncated/unclosed '(Tech: NAME' too."""
    return re.sub(r"\s*\(\s*Tech\s*:[^)]*\)?\s*$", "", desc or "", flags=re.IGNORECASE).strip()


def _clean_hist_part_desc(desc: str) -> str:
    """Strip a leading vendor LINE-CODE (letters+digits, e.g. 'WORL001' =
    Worldpac's catalogue code) so the part reads 'Brake Pad Set' not
    'WORL001 Brake Pad Set'. Real alphabetic brand abbreviations (MAN, NGK,
    OES, Bosch) have no digits and are KEPT — they're useful brand info."""
    return re.sub(r"^[A-Z]{2,6}\d{2,4}\s+", "", (desc or "").strip()).strip()


def _clean_hist_partno(pn) -> Optional[str]:
    """Null out a 'part number' that's really a Tekmetric stock STATUS
    ('Inventory', 'Needed', 'Quoted', 'All 7 Received') — those parts simply
    carry no OEM number in the source, and showing the status as a part # is
    misleading."""
    if not pn:
        return None
    s = str(pn).strip()
    if re.fullmatch(r"(Inventory|Needed|Quoted|Received|All\s+\d+\s+Received)",
                    s, flags=re.IGNORECASE):
        return None
    return s or None


def _build_historical_result_payload(job: dict, vehicle, match: dict,
                                     elapsed: float, recalls: list | None = None,
                                     service_skeleton: dict | None = None) -> dict:
    """Phase C — shape a JobResult from a matched HISTORICAL RO.

    The labor lines, part numbers and prices come straight from an estimate
    Sergio built and the customer PAID, so it's ground-truth for this shop.
    Flagged `source: "historical"` with the RO number + match confidence so the
    FE can render a "Matched from your RO #X" banner instead of the live-build
    flow. No ALLDATA / vendor calls run on this path — that's the whole point
    (instant result vs the 4-7 min pipeline). Prices are the historical billed
    prices; a future enhancement can refresh them live from the vendors.
    """
    default_rate = float(job.get("laborRate") or match.get("labor_rate") or 150.0)
    tax_rate = float(job.get("taxRate") or 0.0925)
    ro = match["ro_number"]

    labor_lines: list[dict] = []
    parts_lines: list[dict] = []
    for jb in match.get("jobs") or []:
        job_name = jb.get("name") or ""
        for lab in jb.get("labor") or []:
            hrs = lab.get("hours")
            # Use the shop's CURRENT labor rate × the historical HOURS. The hours
            # are the transferable signal (Sergio's labor time for the job); the
            # old RO's rate may be years stale, which made the displayed total
            # disagree with the "@ $150/h" header. If hours are missing, keep the
            # historically-billed total as a fallback.
            rate = default_rate
            if hrs is not None:
                total = round(float(hrs) * rate, 2)
            else:
                total = lab.get("total")
            labor_lines.append({
                "description": _clean_hist_labor_desc(lab.get("description") or job_name),
                "hours": hrs, "rate": rate, "total": total or 0.0,
                "source": f"Historical RO #{ro}", "skill": None,
                "extractionScreenshot": None,
            })
        for pt in jb.get("parts") or []:
            qty = int(pt.get("qty") or 1)
            total = pt.get("total")
            # Show the per-unit RETAIL price Sergio billed, so qty × unit == the
            # line total. The corpus 'cost' is the shop's WHOLESALE cost while
            # 'total' is retail × qty — displaying cost as the unit price made
            # "qty × $40.10 = $142" look broken. Prefer retail; else derive the
            # unit from total/qty; else fall back to cost.
            # Derive the unit from the BILLED line total first — it's the only
            # value guaranteed consistent with what the customer actually paid
            # (qty × unit == total by construction). 'retail' can be a list/MSRP
            # reference that disagrees with the billed total (seen as
            # "1 × $117.00 = $51.93" in the UI). Fall back retail → cost.
            retail = pt.get("retail")
            if total is not None and qty:
                unit = round(float(total) / qty, 2)
            elif retail is not None:
                unit = round(float(retail), 2)
            else:
                unit = round(float(pt.get("cost") or 0.0), 2)
            if total is None:
                total = round(unit * qty, 2)
            parts_lines.append({
                "description": _clean_hist_part_desc(pt.get("description") or ""),
                "partNumber": _clean_hist_partno(pt.get("part_number")),
                "quantity": qty,
                "cost": unit,
                "markup": 0.0,
                "total": round(float(total), 2),
                "vendor": pt.get("vendor") or "Historical",
                "source": f"Historical RO #{ro}",
            })

    # Recent-price refresh — a matched RO can be years old, and the shop's parts
    # pricing spiked recently (Sergio June 12: "last 5 years the biggest spike").
    # Replace each part's stale unit price with the most recent price the shop
    # billed for the SAME part anywhere in the corpus. Guarded: only a STRICTLY
    # newer price, within a 0.34x–3x band, so a generic-SKU identity collision
    # can't inject a wild number. Fully transparent — the original price + the
    # source RO/date come along so the UI can show "$X (2021) → $Y (2026)".
    from services.historical_corpus import latest_corpus_price, _parse_posted
    ro_ord = _parse_posted(match.get("date_posted"))
    refreshed_count = 0
    for line in parts_lines:
        fresh = latest_corpus_price(line.get("partNumber"), line.get("description"))
        if not fresh:
            continue
        if ro_ord and fresh["date_ordinal"] <= ro_ord:
            continue  # the matched RO is already as fresh
        old_unit = float(line.get("cost") or 0.0)
        new_unit = float(fresh["unit"])
        if old_unit <= 0 or not (0.34 <= new_unit / old_unit <= 3.0):
            continue  # implausible swing → likely a wrong identity, skip
        qty = int(line.get("quantity") or 1)
        line["originalCost"] = old_unit
        line["originalTotal"] = line.get("total")
        line["cost"] = new_unit
        line["total"] = round(new_unit * qty, 2)
        line["priceRefreshed"] = True
        line["priceDate"] = fresh["date"]
        line["priceSourceRO"] = fresh["ro_number"]
        refreshed_count += 1

    labor_total = round(float(match.get("labor_total") or
                              sum(l["total"] for l in labor_lines)), 2)
    # When any line was refreshed the stored aggregate is stale — recompute from
    # the (now-updated) lines and don't defer to the old billed grand total.
    if refreshed_count:
        parts_total = round(sum(float(p["total"]) for p in parts_lines), 2)
    else:
        parts_total = round(float(match.get("parts_total") or
                                  sum(p["total"] for p in parts_lines)), 2)
    subtotal = round(labor_total + parts_total, 2)
    stored_total = match.get("total")
    if stored_total and float(stored_total) > subtotal and not refreshed_count:
        grand_total = round(float(stored_total), 2)
        tax_amount = round(grand_total - subtotal, 2)
    else:
        tax_amount = round(subtotal * tax_rate, 2)
        grand_total = round(subtotal + tax_amount, 2)

    conf = float(match.get("confidence") or 0.0)
    # Honest tier routing: "auto" ONLY when the match is essentially certain —
    # the same physical car came back (exact VIN), or a near-identical vehicle
    # (≤2 model-years apart) matched with very high confidence. Everything
    # else goes to advisor review; a wrong auto-approved estimate costs more
    # trust than one extra review click.
    match_tier = match.get("match_tier") or "keyword"
    year_gap = match.get("year_gap")

    # Reconcile the matched RO against the service skeleton. A paid RO can be an
    # INCOMPLETE record of the standard service — e.g. an old front-brake RO
    # billed pads only, missing rotors / wear sensor / carrier bolts (exactly the
    # gap the client flagged on the June 12 call). Surface the missing components
    # so the advisor sees them instead of shipping a thin estimate, and never
    # AUTO-approve a match that doesn't carry every always-required component.
    coverage = _build_skeleton_coverage(service_skeleton, parts_lines,
                                        include_addons=False)
    missing_components: list[str] = []
    coverage_complete = True
    if coverage:
        # Gate on missing PARTS only — the always-required physical components
        # (pads/rotors/carrier bolts). Supply/inspection add-ons (cleaning kit,
        # multi-point) are auto-added at send time and aren't itemised on a paid
        # RO, so their absence must NOT demote an otherwise-complete match. Wear
        # sensors etc. are if-equipped (always_required=False) — also non-gating.
        missing_components = [
            c.get("display_name") for c in coverage.get("components", [])
            if (c.get("kind") or "part") == "part"
            and c.get("always_required", True)
            and not c.get("found_in_extraction")
        ]
        coverage_complete = not missing_components

    if match_tier == "exact_vin" or (conf >= 0.9 and isinstance(year_gap, int)
                                     and year_gap <= 2):
        tier = "auto" if coverage_complete else "advisor_review"
    else:
        tier = "advisor_review"
    return {
        "vehicleInfo": {
            "year": vehicle.year, "make": vehicle.make, "model": vehicle.model,
            "trim": vehicle.trim, "engine": vehicle.engine,
        },
        # Banner data — the FE shows "✨ Built from your historical RO #X".
        "source": "historical",
        "historicalMatch": {
            "roNumber": ro,
            "matchedVehicle": match.get("vehicle"),
            "datePosted": match.get("date_posted"),
            "odometer": match.get("odometer"),
            "confidence": round(conf, 3),
            "vehicleScore": match.get("vehicle_score"),
            "serviceScore": match.get("service_score"),
            "services": match.get("service_names"),
            # When the source RO bundled extra services, we kept only the jobs
            # relevant to this request — surface that so the advisor knows the
            # estimate is a filtered subset of RO #X, not the full visit.
            "filtered": match.get("filtered", False),
            "jobsUsed": match.get("jobs_used"),
            "jobsInRO": match.get("jobs_in_ro"),
            # How the match was made: exact_vin (same physical car) /
            # service_type (canonical classification) / keyword (fallback).
            "matchTier": match_tier,
            "yearGap": year_gap,
            # Skeleton reconciliation — what the standard service expects vs what
            # this RO actually carried. Non-empty `missingComponents` means the
            # advisor should add those lines before sending; it also blocks
            # auto-approval above.
            "coverageComplete": coverage_complete,
            "missingComponents": missing_components,
            # How many part lines had their price refreshed to the shop's most
            # recent corpus price for that part (0 = all prices already current).
            "pricesRefreshed": refreshed_count,
        },
        "laborItems": labor_lines,
        "partsItems": parts_lines,
        "breakdown": {
            "laborTotal": labor_total, "partsTotal": parts_total,
            "subtotal": subtotal, "taxAmount": tax_amount, "total": grand_total,
        },
        "elapsed_sec": round(elapsed, 1),
        "vendorQuotes": [],
        "vendorComparison": {},
        "consensus": {},
        "confidence": {
            "score": round(conf, 3),
            "tier": tier,
            "label": f"Historical Match · RO #{ro} · {round(conf * 100)}%",
            "breakdown": {
                "vehicle_match": match.get("vehicle_score"),
                "service_match": match.get("service_score"),
                "sourcing_note": "historical_ro",
            },
        },
        "recalls": list(recalls or []),
        "suggestedAddOns": [],
        "serviceSkeleton": coverage,
        # Historical matches already carry the shop's real billed price (itself a
        # de-facto flat fee), so the matched total stays the headline.
        "flatFee": None,
        "repairProcedure": {"items": [], "scan_status": "skipped_historical"},
    }


def _build_skeleton_coverage(
    skeleton: dict | None,
    parts_lines: list[dict],
    repair_procedure: dict | None = None,
    include_addons: bool = True,
) -> dict | None:
    """Compare the static skeleton against what ALLDATA actually extracted.

    For each expected component, attempt a loose name match against the
    extracted parts. Output per-component {expected, found, matched_part?}
    plus a headline `coverage_pct` so the FE can show "5/8 expected
    components found (62%)" — making missing line items visible to the
    advisor instead of silently shipping a $430 estimate for a $1,000 job.

    Returns None when no skeleton was matched, so the FE hides the panel
    instead of showing a meaningless "0% coverage" badge.
    """
    if not skeleton:
        return None

    # Live path counts add-ons (cleaning kit, multi-point) because the worker
    # auto-injects them as part lines — so they SHOULD be found. The historical
    # path doesn't inject them (the matched RO is the shop's real billed work),
    # so counting them would falsely read the coverage down; callers pass
    # include_addons=False there to score against physical components only.
    expected = list(skeleton.get("components") or [])
    if include_addons:
        expected += (skeleton.get("addons") or [])
    extracted_names = [
        (p.get("description") or "").lower() for p in (parts_lines or [])
    ]

    # Repair-Procedure item index (task #13). Lets us promote a skeleton
    # component from MISSING to CONFIRMED-BY-REPAIR-PROCEDURE when the
    # ALLDATA repair article literally tells the tech to renew/replace
    # that part — even when the Parts table didn't list it. This is the
    # mechanism that closes Sergio's $430→$1000 gap.
    rp_items = (repair_procedure or {}).get("items") or []
    rp_keys = {(it.get("component_key") or "").lower() for it in rp_items}
    rp_phrases = [(it.get("component_phrase") or "").lower() for it in rp_items]

    component_status = []
    found_count = 0
    for c in expected:
        # Name-match heuristic: any of the component's display_name tokens
        # OR vendor_search_terms appearing in any extracted part name.
        candidates = [c.get("display_name", "").lower()]
        candidates.extend([s.lower() for s in (c.get("vendor_search_terms") or [])])
        candidates.extend([k.lower() for k in (c.get("alldata_keywords") or [])])
        # Strip empties + dedup
        candidates = [t.strip() for t in candidates if t and len(t.strip()) > 2]

        matched_idx = None
        for i, en in enumerate(extracted_names):
            if not en:
                continue
            # Token-overlap match: any candidate appears as substring of
            # the extracted name, or vice versa for short names.
            if any(t in en or (len(en) > 3 and en in t) for t in candidates):
                matched_idx = i
                break

        # R-cell confirmation: skeleton's `key` matches a repair-procedure
        # component_key (e.g. skeleton key 'brake_carrier_bolts' →
        # rp_key 'carrier_bolt'), OR a vendor_search_term substring
        # matches an rp phrase. Generous to favour catching items.
        rp_match = None
        skel_key = (c.get("key") or "").lower()
        for rp_it in rp_items:
            rp_key = (rp_it.get("component_key") or "").lower()
            rp_phrase = (rp_it.get("component_phrase") or "").lower()
            # Direct key contains check (carrier_bolt in brake_carrier_bolts)
            if rp_key and (rp_key in skel_key or skel_key in rp_key):
                rp_match = rp_it
                break
            # Phrase against candidates (rp 'crush washer' vs candidate 'drain plug crush washer')
            if rp_phrase and any(rp_phrase in cnd or cnd in rp_phrase for cnd in candidates):
                rp_match = rp_it
                break

        is_found = matched_idx is not None or rp_match is not None
        if is_found:
            found_count += 1
        component_status.append({
            "key": c.get("key"),
            "display_name": c.get("display_name"),
            "kind": c.get("kind"),
            "default_qty": c.get("default_qty"),
            "always_required": c.get("always_required", True),
            "reason": c.get("reason"),
            "default_cost": c.get("default_cost"),
            "found_in_extraction": matched_idx is not None,
            "confirmed_by_repair_procedure": rp_match is not None,
            "repair_procedure_action": (rp_match or {}).get("action"),
            "repair_procedure_qty": (rp_match or {}).get("quantity"),
            "matched_part_description": (
                parts_lines[matched_idx].get("description") if matched_idx is not None else None
            ),
        })

    # Coverage % is calculated over ALWAYS-REQUIRED items only — optional
    # if-equipped components (wear sensors etc.) shouldn't drag the
    # number down when the vehicle legitimately doesn't have them.
    required = [c for c in component_status if c["always_required"]]
    required_found = sum(1 for c in required if c["found_in_extraction"])
    coverage_pct = round(100.0 * required_found / len(required), 1) if required else 100.0

    return {
        "service_type": skeleton.get("service_type"),
        "display_name": skeleton.get("display_name"),
        "expected_estimate_range": skeleton.get("expected_estimate_range"),
        "notes": skeleton.get("notes"),
        "coverage_pct": coverage_pct,
        "components_found": required_found,
        "components_required": len(required),
        "components": component_status,
    }


async def _process_job(client: httpx.AsyncClient, hermes: HermesClient, job: dict) -> None:
    job_id = job["job_id"]
    vin = job["vin"]
    complaint = job["serviceRequest"]
    logger.info(f"[{job_id}] VIN={vin}  '{complaint[:80]}'")
    t0 = time.time()

    try:
        # 1+2. Hermes parse (intent extraction) and NHTSA VIN decode are
        # independent — running them in parallel saves the NHTSA call's
        # wall-clock (typically 30-60s on slow days, since the public API
        # has no SLA). Hermes is a sync Ollama call so we wrap it in
        # asyncio.to_thread; NHTSA is already async.
        await _post_progress(client, job_id, "Parsing complaint + decoding VIN", 20)
        job_dict, vehicle = await asyncio.gather(
            asyncio.to_thread(hermes.parse_job_spec, complaint, vin),
            decode_vin(vin),
        )
        spec = JobSpec(**job_dict)
        logger.info(f"[{job_id}] decoded: {vehicle.year} {vehicle.make} {vehicle.model}")

        # 2c. Service-type skeleton (task #12). Map the parsed JobSpec to a
        # canonical service_type and load its expected-components skeleton.
        # This is the BASELINE list of what the service typically needs
        # (e.g. brakes = pads + rotors + carriers + sensors + cleaning kit)
        # per the client's verbatim definition from the June 6 meeting.
        # ALLDATA's Repair Procedure scan (task #13) will refine this with
        # actual `renew`/`replace` items pulled from the live article.
        from services.service_skeleton import skeleton_for_job
        service_skeleton = skeleton_for_job(spec)
        if service_skeleton:
            logger.info(
                f"[{job_id}] service skeleton: {service_skeleton['service_type']!r} "
                f"({service_skeleton['display_name']}) — "
                f"{len(service_skeleton['components'])} expected components, "
                f"{len(service_skeleton['addons'])} add-ons, "
                f"target range ${service_skeleton['expected_estimate_range'][0]}-"
                f"${service_skeleton['expected_estimate_range'][1]}"
            )
        else:
            logger.info(f"[{job_id}] no service skeleton match — falling back to "
                        f"ALLDATA-extracted parts only")

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

        # 2d. Phase C — HISTORICAL RO corpus check. Before spending 4-7 min on
        # ALLDATA + vendors, see if Sergio already built (and got paid for) an
        # estimate on this vehicle + service. A confident match returns the
        # shop's own past work INSTANTLY (< 1s) with a "Matched from your RO #X"
        # banner. Conservative — only fires on a strong (vehicle × service)
        # score; otherwise we fall straight through to the live pipeline below.
        try:
            from services.historical_corpus import match_job
            hist = match_job(vehicle.year, vehicle.make, vehicle.model,
                             complaint, vin=vin)
        except Exception as e:
            logger.warning(f"[{job_id}] corpus match error (non-fatal): {e}")
            hist = None
        if hist:
            logger.info(
                f"[{job_id}] HISTORICAL MATCH RO#{hist['ro_number']} "
                f"conf={hist['confidence']} (veh={hist['vehicle_score']} "
                f"svc={hist['service_score']}) — instant result, skipping ALLDATA"
            )
            await _post_progress(
                client, job_id,
                f"Matched your historical RO #{hist['ro_number']}", 90)
            try:
                recalls = await _get_recalls(vehicle.make, vehicle.model, vehicle.year)
            except Exception:
                recalls = []
            result = _build_historical_result_payload(
                job, vehicle, hist, time.time() - t0, recalls=recalls,
                service_skeleton=service_skeleton)
            cov = (result.get("serviceSkeleton") or {})
            hm = result.get("historicalMatch", {})
            miss = hm.get("missingComponents") or []
            if miss:
                logger.info(
                    f"[{job_id}] historical RO#{hist['ro_number']} coverage "
                    f"{cov.get('coverage_pct')}% — missing {len(miss)} expected "
                    f"component(s): {', '.join(miss)} → advisor_review")
            if hm.get("pricesRefreshed"):
                logger.info(
                    f"[{job_id}] refreshed {hm['pricesRefreshed']} part price(s) "
                    f"to the shop's most recent corpus pricing")
            await _post_result(client, job_id, result)
            logger.info(f"[{job_id}] DONE (historical RO#{hist['ro_number']}) "
                        f"in {time.time() - t0:.1f}s")
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

        # 4. ALLDATA labor + parts extraction. Cache check first — task #16
        # lets a repeat (VIN, service_type, complaint) skip the 4-7 min
        # ALLDATA vision agent entirely (the single largest contributor to
        # job wall-clock). Vendor pricing + recalls are always live; only
        # the ALLDATA portion is cached.
        from services.result_cache import get_cached_result, store_result
        service_type_key = (service_skeleton or {}).get("service_type") if service_skeleton else None
        cached_meta = get_cached_result(vin, service_type_key, complaint)
        labor = None
        meta = None
        if cached_meta:
            try:
                # Reconstruct LaborResult from cached dict so downstream code
                # (which expects an object) keeps working.
                from models.job_spec import LaborResult
                lr = cached_meta.get("labor")
                if lr:
                    labor = LaborResult(**lr)
                meta = cached_meta.get("meta") or {}
                op = labor.operation if labor else None
                hrs = labor.hours if labor else None
                logger.info(
                    f"[{job_id}] ALLDATA cache HIT — "
                    f"labor={op!r} hours={hrs} — skipping agent"
                )
                await _post_progress(
                    client, job_id, "Loaded ALLDATA result from cache", 70
                )
            except Exception as e:
                logger.warning(f"[{job_id}] cache hit but rehydration failed: {e}")
                labor = None
                meta = None

        if labor is None:
            await _post_progress(client, job_id, "Running ALLDATA vision agent (Gemini)", 50)
            try:
                labor, meta = await asyncio.wait_for(
                    lookup_labor_time(spec, vehicle, max_steps=25,
                                      service_skeleton=service_skeleton),
                    timeout=JOB_TIMEOUT,
                )
            except asyncio.TimeoutError:
                err = f"Timed out after {JOB_TIMEOUT}s — ALLDATA agent did not finish (site slow or stuck)."
                logger.error(f"[{job_id}] {err}")
                await _post_failure(client, job_id, err)
                return
            # Persist a successful run for future repeat-VIN hits. Cache
            # only when extraction actually produced a labor row AND the
            # vehicle-mismatch guard didn't trip — never cache a failed
            # extraction (it would poison the next legitimate run).
            if labor and not (meta or {}).get("fail_reason"):
                try:
                    cache_payload = {
                        "labor": labor.model_dump(),
                        "meta": meta,
                    }
                    store_result(vin, service_type_key, complaint, cache_payload)
                except Exception as e:
                    logger.warning(f"[{job_id}] cache store failed (non-fatal): {e}")
        # Below this point `labor` and `meta` are populated either from
        # the cache hit OR a successful agent run. Both paths join here.

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
            # Specific failure modes flagged by the agent itself (set in
            # alldata_agent.lookup_labor_time when a hard guard trips).
            fail_reason = (meta or {}).get("fail_reason") or ""
            lowered = last_note.lower()
            if fail_reason == "vehicle_mismatch_on_extract_page":
                vin_tail = (meta or {}).get("target_vin_suffix") or ""
                err = ("ALLDATA agent picked the wrong vehicle — the labor article it "
                       "landed on does not show our target VIN "
                       f"(suffix {vin_tail!r}). The 'Recent Vehicles' list likely had "
                       "a stale row from a previous customer. Re-check the vehicle "
                       "selector and try again.")
            elif any(k in lowered for k in ("log in", "login", "sign in", "session", "logged out")):
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
        # Recalls + add-ons are auxiliary; gather them in parallel so they
        # don't add latency to the critical path. Either failing is silent
        # — the FE simply hides the corresponding banner / panel.
        recalls, suggested_addons = [], []
        try:
            recalls, suggested_addons = await asyncio.gather(
                _get_recalls(vehicle.make, vehicle.model, vehicle.year),
                asyncio.to_thread(_suggest_addons, spec),
            )
        except Exception as e:
            logger.warning(f"[{job_id}] aux data (recalls/addons) failed: {e}")
        if recalls:
            logger.info(f"[{job_id}] {len(recalls)} active NHTSA recall(s) for vehicle")
        if suggested_addons:
            logger.info(f"[{job_id}] {len(suggested_addons)} recommended add-on(s) for job type")
        elapsed = time.time() - t0
        result = _build_result_payload(job, vehicle, labor, meta, elapsed,
                                       vendor_quotes=vendor_quotes_dicts,
                                       vendor_comparison=vendor_comparison,
                                       recalls=recalls,
                                       suggested_addons=suggested_addons,
                                       service_skeleton=service_skeleton)

        await _post_result(client, job_id, result)
        logger.info(
            f"[{job_id}] DONE  '{labor.operation}' {labor.hours}h  "
            f"parts={len(result['partsItems'])}  total=${result['breakdown']['total']:.2f}  "
            f"{elapsed:.1f}s"
        )

        # Phase E NOTE: raw auto-generated estimates are deliberately NOT
        # ingested into the historical corpus here. An unreviewed build can be
        # over-stuffed (ALLDATA lists conditional parts like calipers), and
        # ingesting it made that draft come back as a high-confidence
        # "historical match" on the next identical query — garbage promoted to
        # ground truth. Ingest now happens in _process_tekmetric_job AFTER the
        # advisor approves and pushes the estimate (approval = ground truth).

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

    # Route to REST API path when TEKMETRIC_USE_API is truthy; otherwise the
    # browser-driven vision agent (the legacy default). This gate lets the
    # API migration be validated one job at a time without breaking the
    # browser fallback that already works once an operator has solved the
    # reCAPTCHA challenge via noVNC.
    use_api = (os.environ.get("TEKMETRIC_USE_API", "") or "").lower() in {"1", "true", "yes", "on"}
    if use_api:
        await _progress("Pushing to Tekmetric via REST API", 20)
        try:
            from services.tekmetric_api import push_estimate_api
            ok, result = await asyncio.wait_for(
                push_estimate_api(estimate), timeout=60,
            )
        except asyncio.TimeoutError:
            await _fail("Tekmetric API push timed out after 60s")
            return
        except Exception as e:
            import traceback
            logger.error(f"[{job_id}] Tekmetric API push EXCEPTION: {e}\n{traceback.format_exc()}")
            await _fail(f"{type(e).__name__}: {str(e)[:300]}")
            return
    else:
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

    # Phase E — ingest the APPROVED estimate into the historical corpus, under
    # the REAL Tekmetric RO number the push just produced. This is the only
    # ingest point: the advisor reviewed and pushed it, so it's ground truth
    # (raw auto-builds are never ingested — see _process_job). Non-fatal.
    try:
        from services.historical_corpus import ingest_worker_result
        vi = estimate.get("vehicleInfo") or {}
        ing_key = ingest_worker_result(
            vi.get("vin") or estimate.get("vin"),
            vi.get("year"), vi.get("make"), vi.get("model"),
            estimate.get("serviceRequest") or "",
            {"laborItems": estimate.get("laborItems") or [],
             "partsItems": estimate.get("partsItems") or [],
             "breakdown": estimate.get("breakdown") or {}},
            ro_number=str(result.get("ro_number") or "") or None,
        )
        if ing_key:
            logger.info(f"[{job_id}] approved estimate ingested into corpus as {ing_key}")
    except Exception as e:
        logger.warning(f"[{job_id}] corpus ingest after push failed (non-fatal): {e}")


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
