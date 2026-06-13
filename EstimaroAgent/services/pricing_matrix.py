"""Shop pricing matrices — parts markup by cost bracket, labor markup by hours.

Source: the client's Tekmetric "Parts Matrix" (General Parts Matrix, auto-applied
to parts) and "Labor Matrix" (Default Labor Matrix), captured from screenshots on
the June 12 2026 call. These mirror exactly what Tekmetric auto-applies when a
part / labor row is added to a repair order, so an Estimaro estimate lands on the
same number the shop's own software would bill instead of a flat placeholder
markup.

Both matrices use Tekmetric's *compound* method: the multiplier is applied to the
line's base amount (the part's unit cost for parts; hours × rate for labor).

  parts:  retail_unit = cost  × parts_multiplier_for_cost(cost)
  labor:  line_total  = hours × rate × labor_multiplier_for_hours(hours)

The shop currently runs a single matrix. If per-shop / multi-matrix support is
needed later, key these tables by shop_id (from Backend shop_settings) and pass
the resolved table through the job config rather than importing the constant.

NOTE on the parts first bracket: the Tekmetric UI labelled $0–$10 as "800%
markup", but its own Multiplier (4.00x) and Gross-Profit (75%) columns — and the
owner's verbal "300%" on the call — all agree it is a 4.00x / +300% bracket. The
"800%" cell is a display artifact; the multiplier column is authoritative here.
"""
from __future__ import annotations

import math

# Parts Matrix — (inclusive cost ceiling, multiplier). The multiplier INCLUDES
# the cost itself (4.00x = cost + 300% markup). Brackets are evaluated low→high;
# the first ceiling a cost is <= wins. Boundaries match the Tekmetric UI exactly:
# $0.00–$10.00, $10.01–$50.00, $50.01–$110.00, $110.01–$175.00, $175.01–$750.00,
# $750.01+.
PARTS_MATRIX: list[tuple[float, float]] = [
    (10.00,         4.00),   # $0.00 – $10.00    → +300% markup (GP 75%)
    (50.00,         2.75),   # $10.01 – $50.00   → +175% markup (GP 63.64%)
    (110.00,        2.50),   # $50.01 – $110.00  → +150% markup (GP 60%)
    (175.00,        2.25),   # $110.01 – $175.00 → +125% markup (GP 55.56%)
    (750.00,        2.00),   # $175.01 – $750.00 → +100% markup (GP 50%)
    (math.inf,      1.85),   # $750.01 +         → +85%  markup (GP 45.95%)
]

# Labor Matrix — (inclusive hours ceiling, multiplier). Applied to the labor
# extended amount (hours × rate). Markup ramps +2%/hr from 3% up to a 19% plateau
# at 8–10 hrs, then eases back to 15% for long jobs — taken from the Markup column
# of the Default Labor Matrix (the UI's multiplier column had OCR-grade rounding
# noise like "1.18x" for 13%, so the Markup% column is the source of truth).
LABOR_MATRIX: list[tuple[float, float]] = [
    (1.0,       1.03),   # 0.00 – 1.0 h   → +3%
    (2.0,       1.05),   # 1.01 – 2.0 h   → +5%
    (3.0,       1.07),   # 2.01 – 3.0 h   → +7%
    (4.0,       1.09),   # 3.01 – 4.0 h   → +9%
    (5.0,       1.11),   # 4.01 – 5.0 h   → +11%
    (6.0,       1.13),   # 5.01 – 6.0 h   → +13%
    (7.0,       1.15),   # 6.01 – 7.0 h   → +15%
    (8.0,       1.17),   # 7.01 – 8.0 h   → +17%
    (9.0,       1.19),   # 8.01 – 9.0 h   → +19%
    (10.0,      1.19),   # 9.01 – 10.0 h  → +19%
    (11.0,      1.17),   # 10.01 – 11.0 h → +17%
    (12.0,      1.17),   # 11.01 – 12.0 h → +17%
    (13.0,      1.15),   # 12.01 – 13.0 h → +15%
    (math.inf,  1.15),   # 13.01 +        → +15%
]


def _lookup(table: list[tuple[float, float]], value: float) -> float:
    """First bracket whose inclusive ceiling the value falls within."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v < 0:
        v = 0.0
    for ceiling, mult in table:
        if v <= ceiling:
            return mult
    return table[-1][1]


def parts_multiplier_for_cost(cost: float) -> float:
    """Tekmetric parts multiplier for a part's unit cost (e.g. 2.75)."""
    return _lookup(PARTS_MATRIX, cost)


def parts_markup_pct_for_cost(cost: float) -> float:
    """Parts markup as a percentage (e.g. 175.0 for the $10.01–$50 bracket)."""
    return round((parts_multiplier_for_cost(cost) - 1.0) * 100.0, 2)


def labor_multiplier_for_hours(hours: float) -> float:
    """Tekmetric labor multiplier for a labor row's hours (e.g. 1.07)."""
    return _lookup(LABOR_MATRIX, hours)


def labor_markup_pct_for_hours(hours: float) -> float:
    """Labor markup as a percentage (e.g. 7.0 for the 2.01–3.0 hr bracket)."""
    return round((labor_multiplier_for_hours(hours) - 1.0) * 100.0, 2)


if __name__ == "__main__":
    print("PARTS — cost → multiplier / markup%")
    for c in (5, 10, 10.01, 40, 50, 75, 110, 150, 200, 750, 751, 1200):
        print(f"  ${c:>8.2f} → {parts_multiplier_for_cost(c):.2f}x  "
              f"(+{parts_markup_pct_for_cost(c):g}%)")
    print("\nLABOR — hours → multiplier / markup%")
    for h in (0.5, 1, 1.3, 2.5, 5, 6, 8.5, 9.5, 10.5, 12.5, 14):
        print(f"  {h:>4}h → {labor_multiplier_for_hours(h):.2f}x  "
              f"(+{labor_markup_pct_for_hours(h):g}%)")
