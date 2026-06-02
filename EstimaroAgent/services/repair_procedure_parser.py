"""Parse ALLDATA's repair-procedure text into a structured component list.

This is task #13's pure-logic core. The ALLDATA agent navigates to the
"R" (Repair) cell after labor extraction, captures the article's full
body text, and hands it to `parse_repair_procedure()` here. The parser
scans for replacement-indicating keywords — `renew`, `replace`,
`torque to yield`, `one-time use` — and returns a structured list of
components that the agent has been told must be swapped during the job.

Why pure text parsing (no LLM): the vocabulary ALLDATA uses is tiny
and stable. BMW/Volvo say "renew", domestic OEMs say "replace",
torque-to-yield is a literal phrase. A regex pass is deterministic
(matches Sergio's preference, June 6: "100% accuracy"), free, and
runs in milliseconds — every LLM hop here adds latency and noise
without adding signal.

Client context (Sergio, May 1 2026 shocks demo):
  "All data utilizes the word 'renew' indicating to replace pretty
   much... the key words in literature that we're looking for is
   renew and replace... torque to yield is is another one renew nuts
   the nut gets replaced."

So this module exists to encode exactly that scan, run it over the
ALLDATA article text, and surface what the procedure ACTUALLY says
needs replacing — instead of relying on the Parts table alone (which
chronically misses the carrier bolts, anchor nuts, crush washers and
other one-time-use bits that Sergio enumerates manually).
"""
from __future__ import annotations

import re
from typing import Any


# --- keyword patterns ------------------------------------------------------

# Each entry: (regex, action_label). Anchored to word boundaries so 'renew'
# doesn't fire on 'renewable' or 'renewed' (those mean something different).
_KEYWORD_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "renew screws", "renew the bolt" — primary BMW/Volvo replace verb.
    (re.compile(r"\brenew\b", re.IGNORECASE), "renew"),
    # "replace nuts", "replace the gasket" — domestic OEM replace verb.
    (re.compile(r"\breplace\b", re.IGNORECASE), "replace"),
    # "torque to yield" / "torque-to-yield" — implies one-time use, ALL
    # affected fasteners must be replaced.
    (re.compile(r"\btorque[\s\-]+to[\s\-]+yield\b", re.IGNORECASE), "torque_to_yield"),
    # "one-time use" / "one time use" — generic replacement signal.
    (re.compile(r"\bone[\s\-]time[\s\-]use\b", re.IGNORECASE), "one_time_use"),
]

# Component nouns ALLDATA repair procedures typically mention as needing
# replacement. Used to extract the *thing* being renewed from the
# surrounding line — e.g. "renew screws" → component='screws'. Order
# matters: more specific phrases first so "wheel bearing" beats "bearing".
_COMPONENT_VOCAB: list[tuple[str, str]] = [
    # Multi-word phrases first (longest match wins)
    ("crush washer", "crush_washer"),
    ("drain plug gasket", "drain_plug_gasket"),
    ("carrier bolt", "carrier_bolt"),
    ("caliper bolt", "caliper_bolt"),
    ("wheel bearing", "wheel_bearing"),
    ("brake pad sensor", "brake_pad_sensor"),
    ("wear sensor", "wear_sensor"),
    ("pad sensor", "wear_sensor"),
    ("brake pad", "brake_pad"),
    ("brake disc", "brake_rotor"),
    ("brake rotor", "brake_rotor"),
    ("brake hose", "brake_hose"),
    ("brake fluid", "brake_fluid"),
    ("oil filter", "oil_filter"),
    ("oil pan gasket", "oil_pan_gasket"),
    ("pan gasket", "pan_gasket"),
    ("anchor bolt", "anchor_bolt"),
    ("anchor screw", "anchor_screw"),
    ("strut mount", "strut_mount"),
    ("shock mount", "shock_mount"),
    ("spring pad", "spring_pad"),
    ("bump stop", "bump_stop"),
    ("self-locking nut", "self_locking_nut"),
    ("self locking nut", "self_locking_nut"),
    ("locking nut", "self_locking_nut"),
    ("cotter pin", "cotter_pin"),
    ("sealing ring", "sealing_ring"),
    ("o-ring", "o_ring"),
    ("o ring", "o_ring"),
    ("seat belt", "seat_belt"),
    # Single-word components (very common, last so multi-word wins)
    ("screws", "screw"),
    ("screw", "screw"),
    ("bolts", "bolt"),
    ("bolt", "bolt"),
    ("nuts", "nut"),
    ("nut", "nut"),
    ("gasket", "gasket"),
    ("seals", "seal"),
    ("seal", "seal"),
    ("clips", "clip"),
    ("clip", "clip"),
    ("washers", "washer"),
    ("washer", "washer"),
    ("grommet", "grommet"),
    ("boot", "boot"),
]

# Quantity extraction. ALLDATA writes "renew screws (3)" or "torque
# 250 Nm — 6 bolts". Catch the integer that's clearly counting parts,
# not torque values or Nm units.
_QTY_NEAR_PATTERN = re.compile(
    r"(?:^|\s|\()(\d{1,2})\s*(?:x|×|of|each)?(?=\s|$|\))",
    re.IGNORECASE,
)
# Torque values to EXCLUDE — never confuse "250 Nm" with "250 bolts".
_TORQUE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:nm|n\.m|newton[\s\-]*m|ft[\s\-]?lbs?|lb[\s\-]?ft|in[\s\-]?lbs?|°|degree)\b",
    re.IGNORECASE,
)


# --- main entry point ------------------------------------------------------


def normalize_vision_items(vision_items: list[dict]) -> dict[str, Any]:
    """Convert Gemini's free-form repair-item output to the same shape
    parse_repair_procedure produces from text — so the skeleton merger
    in worker._build_skeleton_coverage works without branching on the
    source.

    Gemini returns:
      [{component, action, quantity, context}, ...]
    We normalize to:
      {items: [{action, component_key, component_phrase, quantity,
                occurrences, contexts}, ...],
       raw_keyword_hits: <int>, scanned_chars: <int>}

    Components are mapped through the same _COMPONENT_VOCAB used for
    text scanning, so 'Carrier Bolt' from Gemini collapses to the same
    component_key as 'carrier bolt' from text parsing.
    """
    if not vision_items:
        return {"items": [], "raw_keyword_hits": 0, "scanned_chars": 0}

    valid_actions = {"renew", "replace", "torque_to_yield", "one_time_use"}
    agg: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in vision_items:
        if not isinstance(raw, dict):
            continue
        comp_text = str(raw.get("component") or "").strip()
        if not comp_text:
            continue
        action = str(raw.get("action") or "").strip().lower()
        if action not in valid_actions:
            # Gemini occasionally returns 'one-time use' etc — normalise.
            if "renew" in action:
                action = "renew"
            elif "torque" in action:
                action = "torque_to_yield"
            elif "one" in action and "time" in action:
                action = "one_time_use"
            elif "replace" in action:
                action = "replace"
            else:
                action = "replace"  # safe default

        # Map free-form component to canonical component_key via vocab.
        comp_lc = comp_text.lower()
        component_key = None
        component_phrase = comp_text
        for phrase, key in _COMPONENT_VOCAB:
            if phrase in comp_lc:
                component_key = key
                component_phrase = phrase  # use canonical phrase for display
                break
        if not component_key:
            # No vocab match — fall back to a slugified version of Gemini's
            # text so unfamiliar parts still aggregate consistently across
            # runs (e.g. 'Cabin Air Filter' -> 'cabin_air_filter').
            component_key = re.sub(r"[^a-z0-9]+", "_", comp_lc).strip("_")
            if not component_key:
                continue

        qty = raw.get("quantity")
        try:
            qty = int(qty) if qty is not None else None
            if qty is not None and not (1 <= qty <= 20):
                qty = None
        except (TypeError, ValueError):
            qty = None

        context = str(raw.get("context") or "").strip()[:180]

        key = (action, component_key)
        if key not in agg:
            agg[key] = {
                "action": action,
                "component_key": component_key,
                "component_phrase": component_phrase,
                "quantity": qty,
                "occurrences": 0,
                "contexts": [],
            }
        agg[key]["occurrences"] += 1
        if qty and (agg[key]["quantity"] is None or qty > agg[key]["quantity"]):
            agg[key]["quantity"] = qty
        if context and len(agg[key]["contexts"]) < 3:
            agg[key]["contexts"].append(context)

    items = sorted(
        agg.values(),
        key=lambda v: (-v["occurrences"], v["component_key"]),
    )
    return {
        "items": items,
        "raw_keyword_hits": len(vision_items),
        "scanned_chars": 0,  # vision doesn't have a char count
    }


def parse_repair_procedure(text: str) -> dict[str, Any]:
    """Scan an ALLDATA repair-procedure article body for replacement items.

    Splits the text into lines/sentences, finds each one that mentions a
    replacement keyword, then locates the component noun in that line
    and (optionally) a quantity. Aggregates by component so 3 lines all
    saying "renew screws" collapse to one entry with qty=3.

    Returns:
      {
        "items": [
          {
            "action": "renew" | "replace" | "torque_to_yield" | "one_time_use",
            "component_key": "carrier_bolt",
            "component_phrase": "carrier bolt",
            "quantity": int | None,
            "occurrences": int,         # how many lines mentioned this
            "contexts": [str, ...],     # up to 3 sample lines for advisor review
          },
          ...
        ],
        "raw_keyword_hits": int,        # total keyword matches (incl. dup lines)
        "scanned_chars": int,
      }
    """
    if not text:
        return {"items": [], "raw_keyword_hits": 0, "scanned_chars": 0}

    # ALLDATA articles arrive as one wall of text; split on sentence
    # boundaries + bullets + newlines. Empty pieces filtered below.
    lines = re.split(r"(?:[.!?\n•\-]\s+)|(?:\.\s*$)", text)
    lines = [ln.strip() for ln in lines if ln and len(ln.strip()) >= 4]

    # Aggregated per component_key — accumulates quantities + sample
    # contexts for the FE to display ("found in 3 places in procedure").
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    total_keyword_hits = 0

    for line in lines:
        # Which keyword(s) fired on this line?
        actions: list[str] = []
        for pat, label in _KEYWORD_PATTERNS:
            if pat.search(line):
                actions.append(label)
        if not actions:
            continue
        total_keyword_hits += len(actions)

        # What component is this line talking about? Take the first
        # (longest) vocabulary match so "wheel bearing" beats "bearing".
        line_lc = line.lower()
        component_phrase: str | None = None
        component_key: str | None = None
        for phrase, key in _COMPONENT_VOCAB:
            if phrase in line_lc:
                component_phrase = phrase
                component_key = key
                break
        if not component_key:
            # Keyword fired but no recognised component — likely a
            # generic instruction like "renew if damaged". Skip.
            continue

        # Quantity extraction — only count integers NOT inside a torque
        # value. Strip torque substrings first so "250 Nm 6 bolts"
        # becomes "6 bolts" not "250 6 bolts".
        line_no_torque = _TORQUE_PATTERN.sub(" ", line)
        qty: int | None = None
        for m in _QTY_NEAR_PATTERN.finditer(line_no_torque):
            try:
                n = int(m.group(1))
                # Plausible part counts only — 50 bolts is unrealistic,
                # likely a misparsed torque or angle. Cap at 20.
                if 1 <= n <= 20:
                    qty = n
                    break
            except ValueError:
                continue

        # Pick the "most actionable" action on this line — renew/replace
        # beat torque_to_yield beat one_time_use for display purposes.
        priority = {"renew": 4, "replace": 3, "torque_to_yield": 2, "one_time_use": 1}
        action = max(actions, key=lambda a: priority.get(a, 0))

        key = (action, component_key)
        if key not in agg:
            agg[key] = {
                "action": action,
                "component_key": component_key,
                "component_phrase": component_phrase,
                "quantity": qty,
                "occurrences": 0,
                "contexts": [],
            }
        agg[key]["occurrences"] += 1
        # Take the maximum observed quantity — if one line says "renew
        # screws" without a number and another says "renew 6 screws",
        # 6 is the meaningful count.
        if qty and (agg[key]["quantity"] is None or qty > agg[key]["quantity"]):
            agg[key]["quantity"] = qty
        if len(agg[key]["contexts"]) < 3:
            # Truncate long contexts so the FE payload stays compact.
            agg[key]["contexts"].append(line[:180])

    items = sorted(
        agg.values(),
        # Most-occurring first — gives the advisor a sense of "ALLDATA
        # mentioned carrier bolts 4 separate times" = important.
        key=lambda v: (-v["occurrences"], v["component_key"]),
    )

    return {
        "items": items,
        "raw_keyword_hits": total_keyword_hits,
        "scanned_chars": len(text),
    }


# --- self-test -------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Sample text patterned on a real BMW front-brake repair procedure.
    sample = """
    Removal procedure for front brake pads.
    1. Raise vehicle on lift.
    2. Remove front wheels.
    3. Disconnect brake pad wear sensor connector.
    4. Remove carrier bolts (2 per side, torque to yield - renew bolts).
    5. Lift caliper away from rotor.
    6. Remove and discard brake pads from carrier.
    7. Inspect brake disc for scoring; replace brake disc if outside spec.

    Installation procedure.
    1. Install new brake pads into carrier.
    2. Reposition caliper.
    3. Renew the carrier bolts (250 Nm, 6 of them - one-time use).
    4. Renew brake pad wear sensor if equipped.
    5. Renew the brake fluid if low after pad-in.
    6. Renew the crush washer on the bleed nipple.

    Torque specifications.
    Carrier bolts: 250 Nm torque to yield - renew after each removal.
    Wheel bolts: 140 Nm.
    """

    result = parse_repair_procedure(sample)
    print(f"Found {len(result['items'])} unique replacement items "
          f"({result['raw_keyword_hits']} raw keyword hits over "
          f"{result['scanned_chars']} chars)\n")
    for it in result["items"]:
        print(f"  [{it['action']:18s}] {it['component_phrase']:25s} "
              f"qty={it['quantity']!s:>5s}  ×{it['occurrences']}  "
              f"({it['contexts'][0][:80]}...)")
