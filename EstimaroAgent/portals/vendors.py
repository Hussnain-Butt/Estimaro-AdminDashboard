"""Vendor price/stock orchestration.

Given the OEM parts ALLDATA produced, query the real distributor portals
(Worldpac, SSF) for buy price + availability, and pick the best quote per part.

Bounded by design for stability: we look up only the top `max_parts` parts that
carry an OEM number, across the enabled vendors, each with its own timeout. So
the total time added to a job stays predictable.

Vendor calls run in parallel up to `VENDOR_CONCURRENCY` (default 2). Each
vendor opens its own CDP browser context, so parallelism trades a bit of
Chrome RAM and CDP traffic for ~50-65% wall-clock reduction on the vendor
phase of a job. Set VENDOR_CONCURRENCY=1 to fall back to serial execution if
Chrome contention ever shows up in production.
"""
import asyncio
import os
from typing import Optional

from loguru import logger

from models.job_spec import VendorQuote
from portals import worldpac, ssf, partslink24
from portals.keyword_variants import variants as keyword_variants


# Order matters — the first vendor a part matches against wins the
# "matched on keyword variant X" log. PartsLink24 is genuine-OEM; Worldpac
# and SSF are aftermarket; the UI ranks by price within each part anyway.
# PartsLink24 is auto-skipped for makes it doesn't cover (see SUPPORTED_MAKES).
VENDOR_MODULES = [partslink24, worldpac, ssf]

# How many ALLDATA parts to price (the most relevant ones). Keep small so a job
# stays within its time budget; raise via env when proven.
MAX_PARTS = int(os.environ.get("VENDOR_MAX_PARTS", "1"))
# Per-vendor lookup budget. 180s was the conservative initial value, but real
# runs show: a vendor that hasn't extracted in 90s isn't going to in 180s
# either — it's already stuck in the picker / re-prompting Gemini. Lowering
# the cap halves worst-case wall-clock when a vendor genuinely can't serve
# the part, and the WorldPac picker-failure detector (see vendors.py retry
# carve-out) means the legitimate-but-slow case is rare.
PER_LOOKUP_TIMEOUT = int(os.environ.get("VENDOR_LOOKUP_TIMEOUT", "90"))
# Max simultaneous vendor lookups. 2 is a safe default — three would put six
# CDP-attached tabs in play (each vendor opens prep + agent), plus Chrome's
# own service workers, which we saw cause connect_over_cdp timeouts on this
# VPS earlier. Promote to 3 only after observed stability under load.
VENDOR_CONCURRENCY = int(os.environ.get("VENDOR_CONCURRENCY", "2"))


async def _lookup_one_vendor(
    mod, vehicle, part_type: str, candidates: list[str],
    oem_hint: str | None, key: str,
) -> list[VendorQuote]:
    """Run one vendor's keyword-variant chain. Returns either real quotes
    (when something matched) or a single not-found placeholder VendorQuote so
    the UI's vendor-comparison block still has a row for every vendor we
    attempted. Never raises — exceptions are caught and converted to a
    not-found row, since `gather_quotes` runs vendors in parallel and we
    don't want one vendor's bad day to drop the others' results.

    Timeout retry policy: if the first variant chain ends with a timeout
    AND no quotes were produced, we wait briefly and retry the FIRST
    candidate one more time. WorldPac in particular has been observed to
    'time out — vendor site was slow' as a transient hiccup that succeeds
    on a second attempt; a single targeted retry restores the multi-source
    coverage that the consensus layer needs without doubling worst-case
    wall-clock for the chronic-failure case (we only retry variant[0],
    not the whole chain)."""
    last_err: str | None = None
    per_vendor_quotes: list[VendorQuote] = []
    for kw in candidates:
        try:
            qs, meta = await mod.lookup(vehicle, kw, oem_hint=oem_hint,
                                        timeout=PER_LOOKUP_TIMEOUT)
            if qs:
                per_vendor_quotes = qs
                if kw != part_type:
                    logger.info(f"[vendors] {mod.PORTAL_NAME} matched on "
                                f"keyword variant {kw!r} (original {part_type!r})")
                break
            # Vendor returned an unconditional "doesn't apply" signal
            # (e.g. PartsLink24 on a non-European VIN, missing brand slug).
            # No retry will ever change that — stop the variant chain.
            if (meta or {}).get("skipped"):
                logger.info(f"[vendors] {mod.PORTAL_NAME} skipped: "
                            f"{meta['skipped']}")
                last_err = f"skipped :: {meta['skipped']}"
                break
            last_err = (meta or {}).get("error", "not found")
            # Retries help when the vendor's vocabulary rejected the keyword
            # (no_part_type / no_extraction); they DO NOT help when the agent
            # ran out of time exploring the UI, where a different keyword
            # just burns another full timeout.
            if any(tag in last_err.lower() for tag in
                   ("timeout", "agent_crash", "login_failed", "session_expired",
                    "no_brand_app", "direct_entry_missing", "prep_failed")):
                logger.info(f"[vendors] {mod.PORTAL_NAME} {kw!r} hit "
                            f"non-keyword failure ({last_err}); not retrying variants")
                break
            logger.info(f"[vendors] {mod.PORTAL_NAME} no results for "
                        f"{kw!r} ({last_err}); trying next variant")
        except Exception as e:
            last_err = f"error: {str(e)[:120]}"
            logger.warning(f"[vendors] {mod.PORTAL_NAME} lookup failed for "
                           f"{kw!r}: {e}")
            # Hard exceptions are also not keyword-fixable — stop.
            break

    # One-shot transient-timeout retry. Only fires when the first pass
    # produced zero quotes AND the last error was a timeout — i.e. the
    # vendor was reachable, the agent just ran out of clock. Sleeping
    # briefly between attempts lets the vendor site recover and avoids
    # hammering it; 20s is short enough to keep the overall job within
    # budget when paired with VENDOR_CONCURRENCY > 1.
    #
    # Carve-out: a `vehicle_set_failed` / `year_pick_failed` / `picker_
    # open_failed` is a brittle SELECTOR issue — the vendor's catalogue
    # picker UI can't be driven for THIS year/make/model. Re-trying the
    # same selectors will fail the exact same way and just burn another
    # 180s timeout. Skip the retry, surface the vehicle-coverage error
    # straight to the FE.
    deterministic_vehicle_fail = (last_err and any(
        tag in last_err.lower() for tag in
        ("vehicle_set_failed", "year_pick_failed", "picker_open_failed")
    ))
    if (not per_vendor_quotes and last_err
            and "timeout" in last_err.lower() and candidates
            and not deterministic_vehicle_fail):
        logger.info(f"[vendors] {mod.PORTAL_NAME} timed out on first pass — "
                    f"retrying {candidates[0]!r} once after 20s cool-off")
        await asyncio.sleep(20)
        try:
            qs, meta = await mod.lookup(vehicle, candidates[0],
                                        oem_hint=oem_hint,
                                        timeout=PER_LOOKUP_TIMEOUT)
            if qs:
                per_vendor_quotes = qs
                logger.info(f"[vendors] {mod.PORTAL_NAME} retry SUCCEEDED — "
                            f"recovered {len(qs)} quote(s)")
            else:
                retry_err = (meta or {}).get("error") or "still no results"
                logger.info(f"[vendors] {mod.PORTAL_NAME} retry failed: "
                            f"{retry_err}")
                last_err = f"{last_err} (retry: {retry_err})"
        except Exception as e:
            logger.warning(f"[vendors] {mod.PORTAL_NAME} retry raised: {e}")
            last_err = f"{last_err} (retry_exception: {str(e)[:60]})"

    if per_vendor_quotes:
        return per_vendor_quotes
    return [VendorQuote(
        vendor=mod.PORTAL_NAME, requested_part=key,
        matched_part_name=part_type, found=False,
        note=f"{last_err or 'not found'} (tried: {', '.join(repr(c) for c in candidates)})",
    )]


async def gather_quotes(vehicle, part_type: str,
                        oem_hint: str | None = None,
                        complaint: str | None = None) -> list[VendorQuote]:
    """Price one part type across the aftermarket distributors by VEHICLE +
    part type (the reliable path — they do not index by genuine OEM number).
    Runs up to `VENDOR_CONCURRENCY` vendors in parallel; a failure on one
    never aborts the others.

    If the first keyword phrasing yields no results, retries with related
    variants from `keyword_variants` (always grounded in the customer's
    complaint so the search never drifts to an unrelated part)."""
    key = oem_hint or part_type
    candidates = keyword_variants(part_type, complaint=complaint)
    if not candidates:
        candidates = [part_type]

    # Concurrency-1 keeps the original serial behaviour for safety / easy
    # rollback via env var. Anything >1 fans out vendors over a semaphore.
    sem = asyncio.Semaphore(max(1, VENDOR_CONCURRENCY))

    async def _bounded(mod):
        async with sem:
            return await _lookup_one_vendor(mod, vehicle, part_type, candidates,
                                            oem_hint, key)

    # return_exceptions=True so a single vendor blowing up never tanks the
    # whole gather — we synthesise a not-found row for the offender instead.
    results = await asyncio.gather(
        *[_bounded(mod) for mod in VENDOR_MODULES],
        return_exceptions=True,
    )

    quotes: list[VendorQuote] = []
    for mod, r in zip(VENDOR_MODULES, results):
        if isinstance(r, Exception):
            logger.error(f"[vendors] {mod.PORTAL_NAME} task raised unhandled "
                         f"exception: {type(r).__name__}: {str(r)[:160]}")
            quotes.append(VendorQuote(
                vendor=mod.PORTAL_NAME, requested_part=key,
                matched_part_name=part_type, found=False,
                note=f"task_exception :: {type(r).__name__}: {str(r)[:120]}",
            ))
            continue
        quotes.extend(r)
    return quotes


def best_quote(quotes: list[VendorQuote], requested_part: str) -> Optional[VendorQuote]:
    """Cheapest in-stock priced quote for a requested part; falls back to the
    cheapest priced, then any found row."""
    cand = [q for q in quotes if q.requested_part == requested_part and q.found]
    priced = [q for q in cand if q.price is not None]
    in_stock = [q for q in priced if q.in_stock]
    pool = in_stock or priced
    if pool:
        return min(pool, key=lambda q: q.price)
    return cand[0] if cand else None


def summarise(quotes: list[VendorQuote]) -> dict:
    """Compact comparison summary keyed by requested part."""
    by_part: dict[str, list[VendorQuote]] = {}
    for q in quotes:
        by_part.setdefault(q.requested_part, []).append(q)
    out = {}
    for part, qs in by_part.items():
        best = best_quote(qs, part)
        out[part] = {
            "best": best.model_dump() if best else None,
            "all": [q.model_dump() for q in qs],
        }
    return out
