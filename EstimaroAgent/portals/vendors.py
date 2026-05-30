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
from portals import worldpac, ssf


# Each entry: (module, enabled). Add PartsLink24 here later if desired.
VENDOR_MODULES = [worldpac, ssf]

# How many ALLDATA parts to price (the most relevant ones). Keep small so a job
# stays within its time budget; raise via env when proven.
MAX_PARTS = int(os.environ.get("VENDOR_MAX_PARTS", "1"))
PER_LOOKUP_TIMEOUT = int(os.environ.get("VENDOR_LOOKUP_TIMEOUT", "180"))


async def gather_quotes(alldata_parts: list[dict]) -> list[VendorQuote]:
    """For the top parts with an OEM number, query each vendor. Failures on one
    vendor never abort the others."""
    quotes: list[VendorQuote] = []
    priced = [p for p in (alldata_parts or []) if (p.get("oem_number") or "").strip()]
    for part in priced[:MAX_PARTS]:
        num = str(part["oem_number"]).strip()
        name = part.get("name")
        for mod in VENDOR_MODULES:
            try:
                qs, meta = await mod.lookup(num, expected_part=name, timeout=PER_LOOKUP_TIMEOUT)
                if qs:
                    quotes.extend(qs)
                else:
                    # Record a 'not found' marker so the UI can show we checked.
                    quotes.append(VendorQuote(
                        vendor=mod.PORTAL_NAME, requested_part=num,
                        matched_part_name=name, found=False,
                        note=(meta or {}).get("error", "not found"),
                    ))
            except Exception as e:
                logger.warning(f"[vendors] {mod.PORTAL_NAME} lookup failed for {num}: {e}")
                quotes.append(VendorQuote(
                    vendor=mod.PORTAL_NAME, requested_part=num,
                    matched_part_name=name, found=False, note=f"error: {str(e)[:120]}",
                ))
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
