"""Ordered keyword variants for vendor searches.

Aftermarket vendors (SSF, Worldpac) each speak a controlled part-type
vocabulary. The keyword we get from ALLDATA — derived from the customer
complaint — is often more specific or more colloquial than what the vendor's
search box accepts (e.g. "front brake pads" vs the vendor's catalogue entry
"Brake Pad Set"). When the first try misses, we want the agent to retry with a
small set of related candidates rather than fail.

`variants(part_type, complaint=...)` returns an ordered list of keywords from
most-specific (closest to the original complaint wording) to most-general.
Duplicates and overly-broad single words (e.g. "brake") are filtered out.

Design rules:
  * The list always starts with the original part_type — it's the most accurate
    representation of the customer's request; the vendor's NLP often handles it.
  * Each next variant is one well-defined transformation of an earlier one,
    not a free-text reword. This keeps results bounded to the same complaint.
  * Synonyms only between terms that mean the SAME physical part (pad set <->
    pads). We never swap "rotor" for "caliper" etc., since that would price the
    wrong part.
  * Capped at MAX_VARIANTS so a missing-keyword retry never explodes the job
    budget.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional


MAX_VARIANTS = 4

# Position / side qualifiers that vendor catalogues usually drop from part
# names. Stripped only as a retry — the original phrasing is tried first.
_POSITION_QUALIFIERS = {
    "front", "rear", "left", "right", "lh", "rh",
    "driver", "passenger", "side", "upper", "lower", "inner", "outer",
}

# Action words that ALLDATA labour operations tend to suffix onto the part
# name ("Front Brake Pad Replacement", "Oil Filter Service"). They're noise
# for vendor catalogue search, so the qualifier-stripped variant drops them.
_ACTION_WORDS = {
    "replacement", "replace", "service", "servicing", "repair", "repairs",
    "install", "installation", "remove", "removal", "r", "and", "r&r",
}

# Synonyms between phrasings of the SAME physical part. Never map across part
# kinds (e.g. pad <-> rotor). Each rule: a sequence of base tokens -> the
# canonical vendor phrasing.
_SYNONYM_RULES: list[tuple[tuple[str, ...], str]] = [
    # Brake pads
    (("brake", "pads"),       "Brake Pad Set"),
    (("brake", "pad"),        "Brake Pad Set"),
    (("pads",),               "Brake Pad Set"),
    # Brake rotors / discs
    (("brake", "rotors"),     "Brake Disc"),
    (("brake", "rotor"),      "Brake Disc"),
    (("rotors",),             "Brake Disc"),
    (("rotor",),              "Brake Disc"),
    (("brake", "discs"),      "Brake Disc"),
    # Brake calipers
    (("brake", "calipers"),   "Brake Caliper"),
    (("calipers",),           "Brake Caliper"),
    # Filters
    (("oil", "filters"),      "Oil Filter"),
    (("oil", "filter"),       "Oil Filter"),
    (("air", "filters"),      "Air Filter"),
    (("air", "filter"),       "Air Filter"),
    (("cabin", "filters"),    "Cabin Air Filter"),
    (("cabin", "filter"),     "Cabin Air Filter"),
    # Suspension
    (("control", "arms"),     "Control Arm"),
    (("control", "arm"),      "Control Arm"),
    (("shock", "absorbers"),  "Shock Absorber"),
    (("shocks",),             "Shock Absorber"),
    (("struts",),             "Strut Assembly"),
    (("strut",),              "Strut Assembly"),
    # Spark plugs etc.
    (("spark", "plugs"),      "Spark Plug"),
]

# Terms too generic to ever submit on their own — they would return parts from
# every system and waste a step. Removed from the candidate list.
_TOO_GENERIC = {"brake", "pad", "filter", "arm", "plug"}


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]+", s.lower()) if t]


def _strip_qualifiers(part_type: str) -> str:
    toks = [t for t in _tokens(part_type)
            if t not in _POSITION_QUALIFIERS and t not in _ACTION_WORDS]
    return " ".join(toks)


def _apply_synonyms(part_type: str) -> Optional[str]:
    """Return a canonical vendor phrasing for `part_type` if a rule matches,
    else None. Rules are matched longest-first; the FIRST matching rule wins."""
    toks = set(_tokens(part_type))
    for needed, canon in _SYNONYM_RULES:
        if all(n in toks for n in needed):
            return canon
    return None


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for it in items:
        key = it.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def variants(part_type: str, *, complaint: Optional[str] = None) -> List[str]:
    """Return ordered candidate vendor search keywords for `part_type`.

    `complaint` is the customer's free-text complaint (e.g. "front brake pads
    worn, grinding noise"). When supplied, we extract additional part-name
    tokens from it (filtered through the synonym rules), so a vendor that
    rejects the ALLDATA wording can still get a complaint-derived retry.
    """
    candidates: list[str] = []

    # 1. Most accurate — the caller's literal request.
    original = part_type.strip()
    if original:
        candidates.append(original)

    # 2. Qualifier-stripped form (front/rear/left/right etc. removed).
    stripped = _strip_qualifiers(original)
    if stripped and stripped.lower() != original.lower():
        candidates.append(stripped)

    # 3. Canonical vendor phrasing if a synonym rule matches the original or
    #    the stripped form.
    for base in (original, stripped):
        canon = _apply_synonyms(base) if base else None
        if canon:
            candidates.append(canon)

    # 4. Complaint-derived: same transforms applied to the complaint text. The
    #    complaint often names the part more colloquially than the labour line.
    if complaint:
        c_canon = _apply_synonyms(complaint)
        if c_canon:
            candidates.append(c_canon)
        c_stripped = _strip_qualifiers(complaint)
        # Keep only short, part-name-shaped fragments from the complaint.
        if c_stripped and 1 <= len(c_stripped.split()) <= 4:
            candidates.append(c_stripped)

    # Filter and order.
    out = _dedupe_preserve_order(candidates)
    out = [c for c in out if c.lower().strip() not in _TOO_GENERIC]
    return out[:MAX_VARIANTS]
