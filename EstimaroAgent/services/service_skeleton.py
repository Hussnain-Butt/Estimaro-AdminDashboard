"""Service-type classifier + static component skeleton.

Maps a parsed JobSpec to a canonical service_type, then expands to a
skeleton list of components the service typically requires — pads + rotors
+ carriers + sensors + cleaning kit for a brake job, etc.

The skeleton is the BASELINE that ALLDATA's Repair Procedure scan (task
#13) will later refine with actual `renew`/`replace`/`torque-to-yield`
items pulled from the live repair article.

This module exists because the client (Sergio, June 6 2026 meeting)
flagged that the system was missing rotors, carrier bolts, brake pad
sensors and the cleaning kit on a brake job that should have totalled
~$1,000 — the system delivered $430 because it only carried the single
labour row's parts. Every line below comes from the client's verbatim
description of what each service "always" includes (May 1 + June 6 2026
transcripts).
"""
from __future__ import annotations

from typing import Any, Optional
from models.job_spec import JobSpec


# ---------------------------------------------------------------- primitives


def _component(
    key: str,
    display_name: str,
    *,
    kind: str = "part",
    default_qty: int = 1,
    axle_specific: bool = False,
    always_required: bool = True,
    alldata_keywords: Optional[list[str]] = None,
    vendor_search_terms: Optional[list[str]] = None,
    default_cost: Optional[float] = None,
    no_markup: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Compact constructor for component specs. Returning plain dicts (not
    Pydantic) keeps the payload JSON-clean and avoids a round-trip when the
    FE consumes them."""
    return {
        "key": key,
        "display_name": display_name,
        "kind": kind,            # "part" | "labor" | "supply" | "inspection"
        "default_qty": default_qty,
        "axle_specific": axle_specific,
        "always_required": always_required,
        "alldata_keywords": alldata_keywords or [],
        "vendor_search_terms": vendor_search_terms or [],
        "default_cost": default_cost,
        "no_markup": no_markup,
        "reason": reason,
    }


# Shared add-on primitives — referenced by multiple skeletons.

CLEANING_KIT_BRAKE = _component(
    "brake_cleaning_kit", "Brake Cleaning Kit",
    kind="supply", default_qty=1, default_cost=35.00, no_markup=True,
    reason="Standard with every brake service (per shop SOP, Sergio June 6)",
)

MULTI_POINT_INSPECTION = _component(
    "multi_point_inspection", "Multi-Point Inspection",
    kind="inspection", default_qty=1, default_cost=0.0, no_markup=True,
    reason="Free with every service interval",
)

ALIGNMENT_LABOR = _component(
    "alignment_labor", "Wheel Alignment",
    kind="labor", default_qty=1,
    reason="Required after suspension component replacement",
)


# ------------------------------------------------------------------ skeletons


SERVICE_SKELETONS: dict[str, dict[str, Any]] = {
    # ---------- Brakes (Sergio's worked example, June 6) ------------------
    "brake_front_full": {
        "service_type": "brake_front_full",
        "display_name": "Front Brake Service",
        "labor_keywords": [
            "Front Pads", "Front Brake", "Brake Pad", "Front Disc",
            "Brake Pad and Rotor", "Brake Pads and Rotors",
        ],
        "components": [
            _component(
                "front_brake_pads", "Front Brake Pad Set",
                default_qty=1,
                alldata_keywords=["front pad", "brake pad set"],
                vendor_search_terms=["Front Brake Pad Set", "Front Pads"],
                reason="Customer complaint — primary item",
            ),
            _component(
                "front_brake_rotors", "Front Brake Rotor",
                default_qty=2, axle_specific=True,
                alldata_keywords=["front rotor", "brake disc"],
                vendor_search_terms=["Front Brake Rotor", "Brake Disc"],
                reason="Always replaced with pads (Sergio: 'all brake services include 2 brake rotors')",
            ),
            _component(
                "brake_carrier_bolts", "Brake Caliper Carrier Bolt",
                default_qty=4,
                alldata_keywords=["carrier bolt", "renew bolt"],
                vendor_search_terms=["Brake Carrier Bolt", "Caliper Mount Bolt"],
                reason="Torque-to-yield, one-time use (Sergio: 'carrier bolts')",
            ),
            _component(
                "brake_pad_wear_sensor", "Brake Pad Wear Sensor",
                default_qty=1, always_required=False,
                alldata_keywords=["wear sensor", "pad sensor"],
                vendor_search_terms=["Brake Pad Wear Sensor"],
                reason="If equipped (Sergio: 'brake pad sensors if it has it', 1-2 typical)",
            ),
        ],
        "addons": [CLEANING_KIT_BRAKE, MULTI_POINT_INSPECTION],
        "expected_estimate_range": [800, 1200],
        "notes": "Sergio: 'Brake services include pads, rotors, carrier bolts, wear sensors, $35 cleaning kit. Average $1,000.'",
    },

    "brake_rear_full": {
        "service_type": "brake_rear_full",
        "display_name": "Rear Brake Service",
        "labor_keywords": ["Rear Pads", "Rear Brake", "Rear Disc"],
        "components": [
            _component(
                "rear_brake_pads", "Rear Brake Pad Set",
                default_qty=1,
                vendor_search_terms=["Rear Brake Pad Set", "Rear Pads"],
                reason="Customer complaint — primary item",
            ),
            _component(
                "rear_brake_rotors", "Rear Brake Rotor",
                default_qty=2, axle_specific=True,
                vendor_search_terms=["Rear Brake Rotor"],
                reason="Always replaced with pads",
            ),
            _component(
                "rear_carrier_bolts", "Rear Brake Carrier Bolt",
                default_qty=4,
                vendor_search_terms=["Brake Carrier Bolt"],
                reason="Torque-to-yield, one-time use",
            ),
            _component(
                "rear_pad_wear_sensor", "Rear Brake Pad Wear Sensor",
                default_qty=1, always_required=False,
                vendor_search_terms=["Brake Pad Wear Sensor"],
                reason="If equipped",
            ),
        ],
        "addons": [CLEANING_KIT_BRAKE, MULTI_POINT_INSPECTION],
        "expected_estimate_range": [700, 1100],
    },

    # ---------- Oil change (Sergio's range: $200-$400) --------------------
    "oil_change_standard": {
        "service_type": "oil_change_standard",
        "display_name": "Oil Change",
        "labor_keywords": ["Oil Change", "Engine Oil", "Oil and Filter", "Lubrication"],
        "components": [
            _component(
                "engine_oil", "Engine Oil",
                default_qty=1,
                reason="Replaced at every service interval",
            ),
            _component(
                "oil_filter", "Oil Filter",
                default_qty=1,
                alldata_keywords=["oil filter"],
                vendor_search_terms=["Oil Filter"],
                reason="Always replaced with oil",
            ),
            _component(
                "drain_plug_gasket", "Drain Plug Crush Washer",
                default_qty=1,
                alldata_keywords=["drain plug", "crush washer", "sealing ring"],
                vendor_search_terms=["Drain Plug Gasket", "Crush Washer"],
                reason="Single-use on most modern engines",
            ),
        ],
        "addons": [MULTI_POINT_INSPECTION],
        "expected_estimate_range": [200, 400],
        "notes": "Sergio: 'oil changes depending on the car average between 200 to 350-400 bucks.'",
    },

    # ---------- Shocks/struts (Sergio's worked example, May 1) ------------
    "shocks_front": {
        "service_type": "shocks_front",
        "display_name": "Front Shock / Strut Replacement",
        "labor_keywords": [
            "Shock Absorber", "Strut", "Spring Strut", "Front Shock",
            "Front Strut",
        ],
        "components": [
            _component(
                "front_shock_absorber", "Front Shock Absorber",
                default_qty=2, axle_specific=True,
                vendor_search_terms=["Shock Absorber", "Strut Assembly"],
                reason="Customer complaint — primary item",
            ),
            _component(
                "front_spring_pad_upper", "Spring Pad — Upper",
                default_qty=2,
                vendor_search_terms=["Spring Pad Upper"],
                reason="Replaced with shock (Sergio May 1 shocks demo)",
            ),
            _component(
                "front_spring_pad_lower", "Spring Pad — Lower",
                default_qty=2,
                vendor_search_terms=["Spring Pad Lower"],
                reason="Replaced with shock",
            ),
            _component(
                "front_bump_stop", "Bump Stop / Damper",
                default_qty=2,
                vendor_search_terms=["Bump Stop", "Strut Bumper"],
                reason="Replaced with shock",
            ),
            _component(
                "front_shock_mount", "Shock Mount",
                default_qty=2,
                vendor_search_terms=["Shock Mount", "Strut Mount"],
                reason="Replaced with shock",
            ),
            _component(
                "front_anchor_bolts", "Anchor Bolt (renew)",
                default_qty=6, always_required=False,
                vendor_search_terms=["Anchor Bolt", "Strut Bolt"],
                reason="One-time use per ALLDATA repair procedure",
            ),
        ],
        "addons": [ALIGNMENT_LABOR, MULTI_POINT_INSPECTION],
        "expected_estimate_range": [1200, 2500],
        "notes": "Sergio May 1: shock = shock + spring pads + bump stop + shock mount + anchor bolts. Per side x 2.",
    },

    "shocks_rear": {
        "service_type": "shocks_rear",
        "display_name": "Rear Shock / Strut Replacement",
        "labor_keywords": ["Rear Shock", "Rear Strut", "Spring Strut"],
        "components": [
            _component("rear_shock_absorber", "Rear Shock Absorber",
                       default_qty=2, axle_specific=True,
                       vendor_search_terms=["Shock Absorber"],
                       reason="Customer complaint — primary item"),
            _component("rear_spring_pad", "Spring Pad", default_qty=2,
                       vendor_search_terms=["Spring Pad"],
                       reason="Replaced with shock"),
            _component("rear_bump_stop", "Bump Stop", default_qty=2,
                       vendor_search_terms=["Bump Stop"],
                       reason="Replaced with shock"),
            _component("rear_shock_mount", "Shock Mount", default_qty=2,
                       vendor_search_terms=["Shock Mount"],
                       reason="Replaced with shock"),
            _component("rear_anchor_bolts", "Anchor Bolt (renew)",
                       default_qty=6, always_required=False,
                       vendor_search_terms=["Anchor Bolt"],
                       reason="One-time use per ALLDATA repair procedure"),
        ],
        "addons": [ALIGNMENT_LABOR, MULTI_POINT_INSPECTION],
        "expected_estimate_range": [1100, 2300],
    },

    # ---------- Transmission fluid service --------------------------------
    "transmission_fluid_service": {
        "service_type": "transmission_fluid_service",
        "display_name": "Transmission Fluid Service",
        "labor_keywords": [
            "Transmission Fluid", "ATF", "Transmission Service", "Fluid Change",
        ],
        "components": [
            _component("atf", "Transmission Fluid", default_qty=1,
                       reason="Fluid replacement — primary item"),
            _component("transmission_filter", "Transmission Filter",
                       default_qty=1, always_required=False,
                       vendor_search_terms=["Transmission Filter"],
                       reason="If drop-pan (most automatics)"),
            _component("pan_gasket", "Transmission Pan Gasket",
                       default_qty=1, always_required=False,
                       vendor_search_terms=["Pan Gasket"],
                       reason="Single-use on drop-pan transmissions"),
        ],
        "addons": [MULTI_POINT_INSPECTION],
        "expected_estimate_range": [250, 500],
    },

    # ---------- Spark plugs / ignition ------------------------------------
    "spark_plugs": {
        "service_type": "spark_plugs",
        "display_name": "Spark Plug Replacement",
        "labor_keywords": ["Spark Plug", "Ignition", "Plug Replacement"],
        "components": [
            # default_qty=4 is a 4-cyl baseline; per-VIN cylinder count
            # override happens during Repair Procedure scan (task #13).
            _component("spark_plugs", "Spark Plugs",
                       default_qty=4,
                       vendor_search_terms=["Spark Plug"],
                       reason="Set replaced together (baseline 4-cyl; refined per VIN)"),
        ],
        "addons": [MULTI_POINT_INSPECTION],
        "expected_estimate_range": [150, 400],
    },
}


# ---------------------------------------------------------------- classifier


def classify_service(job: JobSpec) -> Optional[str]:
    """Map a Hermes-parsed JobSpec to a canonical service_type key.

    Returns None if no skeleton match — caller falls back to the current
    ALLDATA-parts-only behaviour, so an unrecognised job never breaks
    the pipeline.

    Heuristic order: system field first, then keyword/subsystem text
    refinement. Sergio's most common services are listed first so the
    cheapest path resolves the largest share of traffic.
    """
    system = (job.system or "").lower()
    subsystem = (job.subsystem or "").lower()
    symptom = (job.symptom or "").lower()
    keywords = " ".join(job.keywords or []).lower()
    text = f"{subsystem} {symptom} {keywords}"

    # 1. Brakes — by far Sergio's most common service.
    if system == "braking" or "brake" in text:
        side = "rear" if "rear" in text else "front"
        # Future: "brake_<side>_pads_only" override when customer asks for
        # pads alone. Default to full service per Sergio's standard SOP.
        return f"brake_{side}_full"

    # 2. Oil change.
    if "oil" in text and ("change" in text or "service" in text or "lubricat" in text):
        return "oil_change_standard"
    if system == "engine" and ("oil" in subsystem or "lubric" in subsystem):
        return "oil_change_standard"

    # 3. Suspension / shocks / struts.
    if system == "suspension" or "shock" in text or "strut" in text:
        side = "rear" if "rear" in text else "front"
        return f"shocks_{side}"

    # 4. Transmission fluid service (NOT major transmission repair).
    if system == "transmission" and ("fluid" in text or "service" in text or "atf" in text):
        return "transmission_fluid_service"

    # 5. Spark plugs / ignition.
    if "spark" in text or "ignition" in text:
        return "spark_plugs"

    return None


def skeleton_for_job(job: JobSpec) -> Optional[dict[str, Any]]:
    """Convenience: classify + expand in one call. Returns a deep-copied
    skeleton so callers can mutate without poisoning the SERVICE_SKELETONS
    constant for subsequent runs."""
    st = classify_service(job)
    if not st:
        return None
    raw = SERVICE_SKELETONS.get(st)
    if not raw:
        return None
    import copy
    return copy.deepcopy(raw)


# ---------------------------------------------------------------- self-test


if __name__ == "__main__":
    import json

    test_jobs = [
        JobSpec(system="braking", subsystem="front_brakes", symptom="brake pad noise",
                keywords=["front brake", "pad"]),
        JobSpec(system="braking", subsystem="rear_brakes", symptom="rear brake service"),
        JobSpec(system="engine", subsystem="lubrication", symptom="oil change",
                keywords=["oil", "filter"]),
        JobSpec(system="suspension", subsystem="front_struts", symptom="front shocks worn",
                keywords=["shock", "front"]),
        JobSpec(system="transmission", subsystem="fluid", symptom="transmission service"),
        JobSpec(system="other", subsystem="weird", symptom="something unrelated"),
    ]
    for j in test_jobs:
        sk = skeleton_for_job(j)
        st = classify_service(j)
        print(f"\n{j.system}/{j.subsystem} '{j.symptom}' → {st}")
        if sk:
            n_comp = len(sk["components"])
            n_addon = len(sk["addons"])
            print(f"  → {sk['display_name']}, {n_comp} components, {n_addon} add-ons, "
                  f"expected ${sk['expected_estimate_range'][0]}-${sk['expected_estimate_range'][1]}")
