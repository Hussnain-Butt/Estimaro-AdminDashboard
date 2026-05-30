"""Vendor price/stock orchestration.

Given the OEM parts ALLDATA produced, query the real distributor portals
(Worldpac, SSF) for buy price + availability, and pick the best quote per part.

Bounded by design for stability: we look up only the top `max_parts` parts that
carry an OEM number, across the enabled vendors, each with its own timeout. So
the total time added to a job stays predictable.
"""
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
PER_LOOKUP_TIMEOUT = int(os.environ.get("VENDOR_LOOKUP_TIMEOUT", "180"))


async def gather_quotes(vehicle, part_type: str,
                        oem_hint: str | None = None,
                        complaint: str | None = None) -> list[VendorQuote]:
    """Price one part type across the aftermarket distributors by VEHICLE +
    part type (the reliable path — they do not index by genuine OEM number).
    One call per vendor; a failure on one never aborts the others.

    If the first keyword phrasing yields no results, retries with related
    variants from `keyword_variants` (always grounded in the customer's
    complaint so the search never drifts to an unrelated part)."""
    quotes: list[VendorQuote] = []
    key = oem_hint or part_type
    candidates = keyword_variants(part_type, complaint=complaint)
    if not candidates:
        candidates = [part_type]

    for mod in VENDOR_MODULES:
        last_meta: dict = {}
        last_err: str | None = None
        chosen_keyword: str | None = None
        per_vendor_quotes: list[VendorQuote] = []
        for kw in candidates:
            try:
                qs, meta = await mod.lookup(vehicle, kw, oem_hint=oem_hint,
                                            timeout=PER_LOOKUP_TIMEOUT)
                last_meta = meta or {}
                if qs:
                    per_vendor_quotes = qs
                    chosen_keyword = kw
                    if kw != part_type:
                        logger.info(f"[vendors] {mod.PORTAL_NAME} matched on "
                                    f"keyword variant {kw!r} (original {part_type!r})")
                    break
                # Vendor returned an unconditional "doesn't apply" signal
                # (e.g. PartsLink24 on a non-European VIN, missing brand slug).
                # No retry will ever change that — move on to the next vendor.
                if (meta or {}).get("skipped"):
                    logger.info(f"[vendors] {mod.PORTAL_NAME} skipped: "
                                f"{meta['skipped']}")
                    last_err = f"skipped :: {meta['skipped']}"
                    break
                last_err = (meta or {}).get("error", "not found")
                # Retries help when the vendor's vocabulary rejected the
                # keyword (no_part_type / no_extraction); they DO NOT help
                # when the agent ran out of time exploring the UI, where
                # a different keyword just burns another full timeout.
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
        if per_vendor_quotes:
            quotes.extend(per_vendor_quotes)
        else:
            quotes.append(VendorQuote(
                vendor=mod.PORTAL_NAME, requested_part=key,
                matched_part_name=part_type, found=False,
                note=f"{last_err or 'not found'} (tried: {', '.join(repr(c) for c in candidates)})",
            ))
        _ = chosen_keyword  # available for future telemetry; intentionally unused
        _ = last_meta
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
