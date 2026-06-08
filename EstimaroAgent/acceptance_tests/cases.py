"""Labelled ALLDATA acceptance test cases — task #17.

Each case declares:
  * The customer-facing inputs (VIN + complaint + customer details)
  * The expected SHAPE of the result — labor row name, hour range,
    estimate total range, allowed confidence tier, minimum coverage %
  * `relax` flags for cases where we know a particular check is brittle
    (e.g. vendor coverage low for legacy vehicles)

Pass criteria per case: every declared expectation must pass. Suite
graduation: ≥80% case pass rate over 3 consecutive runs.

Cases are sourced from Sergio's June 6 / May 1 transcripts where he
gave explicit estimate-range expectations:
  * Brake services: ~$1,000 average
  * Oil changes: $200-$400 depending on car
"""
from __future__ import annotations
from typing import Any


# Each case is a flat dict so it can be JSON-dumped for reports.
TEST_CASES: list[dict[str, Any]] = [

    # ----- Brake service, European, legacy year ----------------------------
    # Volvo XC70 2002 — the canonical Sergio test case from the meeting.
    # Worldpac year-picker known-fragile for this year; PartsLink24 demo
    # tier returns no prices. Expect SSF + skeleton add-ons to carry the
    # estimate.
    {
        "name": "volvo_2002_xc70_front_brake",
        "input": {
            "vin": "YV1SZ58D621078311",
            "serviceRequest": "Front brake service",
            "customerName": "Acceptance Test (Volvo)",
            "customerEmail": "test+volvo@germansport.test",
            "customerPhone": "5551112222",
            "odometer": 145000,
        },
        "expected": {
            "service_type": "brake_front_full",
            "labor_operation_contains": ["front pads", "brake pad"],
            "labor_hours_min": 0.7,
            "labor_hours_max": 2.0,
            "total_min": 200.0,
            "total_max": 1300.0,
            "confidence_tier_allowed": ["auto", "advisor_review"],
            "skeleton_coverage_min_pct": 20.0,
            "skeleton_must_include_keys": [
                "front_brake_pads", "front_brake_rotors", "brake_cleaning_kit",
            ],
            "vendor_quotes_min": 1,
            "auto_added_must_include": ["Brake Cleaning Kit"],
        },
        "notes": "Sergio June 6: brake service expected ~$1,000. PartsLink24 "
                 "skips Volvo (European-only), Worldpac year-picker often "
                 "fails for 2002. Wide total band accepts partial-vendor "
                 "runs without failing the case.",
    },

    # ----- Brake service, European, recent year ----------------------------
    # BMW 430i 2019 — modern European, should have better vendor coverage
    # than Volvo. Tests determinism (same VIN+complaint always picks the
    # same labor row).
    {
        "name": "bmw_2019_430i_front_brake",
        "input": {
            "vin": "WBA4J1C53KBM14843",
            "serviceRequest": "Front brake service",
            "customerName": "Acceptance Test (BMW)",
            "customerEmail": "test+bmw@germansport.test",
            "customerPhone": "5552223333",
            "odometer": 65000,
        },
        "expected": {
            "service_type": "brake_front_full",
            "labor_operation_contains": ["front pads", "brake pad"],
            "labor_hours_min": 0.7,
            "labor_hours_max": 2.0,
            "total_min": 200.0,
            "total_max": 1400.0,
            "confidence_tier_allowed": ["auto", "advisor_review"],
            "skeleton_coverage_min_pct": 25.0,
            "vendor_quotes_min": 1,
            "auto_added_must_include": ["Brake Cleaning Kit"],
        },
        "notes": "BMW recent-year case. Determinism check: re-running this "
                 "case 3x in a row must produce identical labor hours.",
    },

    # ----- Oil change ------------------------------------------------------
    # Test the simplest service Sergio mentioned ($200-$400). Volvo VIN
    # reused to leverage cache hit on subsequent runs.
    {
        "name": "volvo_2002_xc70_oil_change",
        "input": {
            "vin": "YV1SZ58D621078311",
            "serviceRequest": "Oil change with filter",
            "customerName": "Acceptance Test (Oil)",
            "customerEmail": "test+oil@germansport.test",
            "customerPhone": "5553334444",
            "odometer": 145500,
        },
        "expected": {
            "service_type": "oil_change_standard",
            "labor_operation_contains": ["oil", "lubricat"],
            "labor_hours_min": 0.3,
            "labor_hours_max": 1.2,
            "total_min": 80.0,
            "total_max": 500.0,
            "confidence_tier_allowed": ["auto", "advisor_review"],
            "skeleton_coverage_min_pct": 33.0,
            "skeleton_must_include_keys": ["oil_filter"],
        },
        "notes": "Sergio June 6: oil changes $200-$400 depending on car. "
                 "Lower bound widened for cases where only filter is in the "
                 "vendor catalog.",
    },
]


# ---------------------------------------------------------------------------


def case_by_name(name: str) -> dict | None:
    for c in TEST_CASES:
        if c.get("name") == name:
            return c
    return None


if __name__ == "__main__":
    import json
    print(f"{len(TEST_CASES)} acceptance test cases defined:")
    for c in TEST_CASES:
        e = c["expected"]
        print(f"  [{c['name']}]")
        print(f"    VIN: {c['input']['vin']}")
        print(f"    Service: {c['input']['serviceRequest']}")
        print(f"    Expected total: ${e['total_min']}-${e['total_max']}")
        print(f"    Tier allowed: {e['confidence_tier_allowed']}")
