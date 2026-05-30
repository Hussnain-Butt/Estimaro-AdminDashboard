"""Aggregated analytics endpoints.

All counters/timeseries the Dashboard, Vendors and Reports pages need are
computed live from the Estimate collection — there is no separate analytics
store, so the numbers are always consistent with the source of truth.

When the collection is small (a fresh install with < 7 days of history) we
still return a well-formed series filled with zeros so the frontend charts
render an empty trend rather than crashing on undefined.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Query

from app.models.customer import Customer
from app.models.estimate import Estimate, EstimateStatus
from app.models.vehicle import Vehicle


router = APIRouter()


# Each successful auto-generated estimate is conservatively assumed to save the
# advisor this many minutes of manual lookup vs. doing ALLDATA + vendor pricing
# by hand. Tunable; shown in the Dashboard "Time Saved" stat.
TIME_SAVED_PER_ESTIMATE_MIN = 50


def _day_floor(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo)


def _last_n_day_buckets(n: int) -> List[datetime]:
    """Return midnight timestamps for the last `n` days (oldest first)."""
    today = _day_floor(datetime.utcnow())
    return [today - timedelta(days=n - 1 - i) for i in range(n)]


def _day_label(d: datetime) -> str:
    return d.strftime("%a")  # Mon/Tue/...


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    summary="Dashboard top-level KPIs + recent activity",
    description=(
        "Returns the four hero stats (estimates today, approval rate, time "
        "saved, parts sourcing summary), the weekly activity line, the per-"
        "advisor approval bar, recent estimate rows and active alerts. All "
        "computed live from the estimate collection."
    ),
)
async def dashboard():
    now = datetime.utcnow()
    today = _day_floor(now)
    week_start = today - timedelta(days=6)

    all_estimates = await Estimate.find_all().to_list()
    today_estimates = [e for e in all_estimates if e.created_at and e.created_at >= today]
    week_estimates = [e for e in all_estimates if e.created_at and e.created_at >= week_start]

    by_status = Counter(str(e.status) for e in all_estimates)
    sent = by_status.get("sent", 0) + by_status.get(EstimateStatus.SENT.value, 0)
    approved = by_status.get("approved", 0) + by_status.get(EstimateStatus.APPROVED.value, 0)
    declined = by_status.get("declined", 0) + by_status.get(EstimateStatus.DECLINED.value, 0)
    decided = approved + declined
    approval_rate = round((approved / decided) * 100) if decided else 0

    # Parts sourcing — count of part-typed items by vendor name.
    vendor_counter: Counter = Counter()
    for est in all_estimates:
        for item in (est.items or []):
            if (item.item_type or "").lower() == "part" and item.vendor_name:
                vendor_counter[item.vendor_name] += 1
    parts_sourcing = " • ".join(f"{v} {n}" for v, n in vendor_counter.most_common(3)) or "—"

    stats = [
        {"key": "estimates_today", "title": "Estimates Today", "value": len(today_estimates)},
        {"key": "approval_rate", "title": "Approval Rate", "value": approval_rate, "suffix": "%"},
        {
            "key": "time_saved",
            "title": "Time Saved",
            "value": approved * TIME_SAVED_PER_ESTIMATE_MIN,
            "suffix": "m",
        },
        {"key": "parts_sourcing", "title": "Parts Sourcing", "value": parts_sourcing},
    ]

    # Weekly activity — estimates created per day in the last 7 days.
    weekly_buckets = _last_n_day_buckets(7)
    per_day: Dict[str, int] = {_day_label(d): 0 for d in weekly_buckets}
    for est in week_estimates:
        label = _day_label(_day_floor(est.created_at))
        if label in per_day:
            per_day[label] += 1
    weekly_activity = [{"label": _day_label(d), "estimates": per_day[_day_label(d)]} for d in weekly_buckets]

    # Approval % by advisor (last 90 days for a stable read).
    cutoff = today - timedelta(days=90)
    advisor_totals: Dict[str, Dict[str, int]] = {}
    for est in all_estimates:
        if not est.created_at or est.created_at < cutoff:
            continue
        if not est.advisor_id:
            continue
        slot = advisor_totals.setdefault(est.advisor_id, {"decided": 0, "approved": 0})
        s = str(est.status)
        if s in (EstimateStatus.APPROVED.value, "approved", EstimateStatus.DECLINED.value, "declined"):
            slot["decided"] += 1
        if s in (EstimateStatus.APPROVED.value, "approved"):
            slot["approved"] += 1
    advisor_approval = [
        {
            "advisor": adv,
            "approval_pct": round((slot["approved"] / slot["decided"]) * 100) if slot["decided"] else 0,
        }
        for adv, slot in advisor_totals.items()
    ]
    advisor_approval.sort(key=lambda r: r["approval_pct"], reverse=True)

    # Alerts — surface things that need operator attention.
    alerts: List[dict] = []
    awaiting = sent  # sent but not yet approved/declined
    if awaiting:
        alerts.append({
            "level": "info",
            "text": f"{awaiting} estimate{'s' if awaiting != 1 else ''} awaiting customer approval",
        })
    expiring = [
        e for e in all_estimates
        if str(e.status) in ("sent", EstimateStatus.SENT.value)
        and e.expires_at and e.expires_at < now + timedelta(days=2)
    ]
    if expiring:
        alerts.append({
            "level": "warning",
            "text": f"{len(expiring)} sent estimate{'s' if len(expiring) != 1 else ''} expiring within 48 hours",
        })

    # Recent estimates — latest 5, joined with vehicle + customer so the row
    # carries display strings the frontend can render without extra fetches.
    recent_sorted = sorted(
        [e for e in all_estimates if e.created_at],
        key=lambda e: e.created_at, reverse=True,
    )[:5]
    needed_vehicle_ids = list({e.vehicle_id for e in recent_sorted if e.vehicle_id})
    vehicles = (
        await Vehicle.find({"_id": {"$in": needed_vehicle_ids}}).to_list()
        if needed_vehicle_ids else []
    )
    vehicle_by_id = {str(v.id): v for v in vehicles}
    needed_customer_ids = list({v.customer_id for v in vehicles if v.customer_id})
    customers = (
        await Customer.find({"_id": {"$in": needed_customer_ids}}).to_list()
        if needed_customer_ids else []
    )
    customer_by_id = {str(c.id): c for c in customers}

    recent_estimates = []
    for est in recent_sorted:
        veh = vehicle_by_id.get(est.vehicle_id) if est.vehicle_id else None
        cust = customer_by_id.get(veh.customer_id) if veh and veh.customer_id else None
        recent_estimates.append({
            "id": str(est.id) if est.id else "",
            "status": str(est.status),
            "customer": cust.full_name if cust else "—",
            "vehicle": veh.display_name if veh else "Vehicle",
            "total": float(est.total or 0),
            "service_request": (est.service_request_text or "")[:80] or None,
        })

    return {
        "stats": stats,
        "weekly_activity": weekly_activity,
        "advisor_approval": advisor_approval,
        "alerts": alerts,
        "recent_estimates": recent_estimates,
        "generated_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@router.get(
    "/vendors",
    summary="Vendor-pricing analytics",
    description=(
        "Usage share, average unit price and average estimate part-total per "
        "vendor — computed from estimate part items. Empty list if no parts "
        "have been sourced yet."
    ),
)
async def vendor_stats():
    estimates = await Estimate.find_all().to_list()
    vendor_usage: Counter = Counter()
    vendor_price_sum: Dict[str, float] = {}
    for est in estimates:
        for item in (est.items or []):
            if (item.item_type or "").lower() != "part":
                continue
            vendor = item.vendor_name or "Unknown"
            vendor_usage[vendor] += 1
            vendor_price_sum[vendor] = vendor_price_sum.get(vendor, 0.0) + float(item.unit_price or 0)

    total_usage = sum(vendor_usage.values())
    usage = [
        {
            "vendor": v,
            "count": cnt,
            "share_pct": round((cnt / total_usage) * 100, 1) if total_usage else 0,
            "avg_unit_price": round(vendor_price_sum[v] / cnt, 2) if cnt else 0,
        }
        for v, cnt in vendor_usage.most_common()
    ]
    avg_part_price = (
        round(sum(vendor_price_sum.values()) / total_usage, 2) if total_usage else 0
    )

    return {
        "usage": usage,
        "avg_part_price": avg_part_price,
        # Delivery time is not yet tracked — surfaced as null so the UI can show
        # an explicit "—" instead of a fabricated number.
        "avg_delivery_min": None,
        "total_part_items": total_usage,
    }


# ---------------------------------------------------------------------------
# Reports — 7-day time series
# ---------------------------------------------------------------------------

@router.get(
    "/reports",
    summary="7-day timeseries for the Reports page",
    description=(
        "All six chart series the Reports page renders, each as "
        "[{label, value}] for the last N days. Defaults to 7."
    ),
)
async def reports(days: int = Query(7, ge=1, le=90)):
    today = _day_floor(datetime.utcnow())
    buckets = _last_n_day_buckets(days)

    estimates = await Estimate.find_all().to_list()
    estimates_by_day: Dict[str, List[Estimate]] = {_day_label(b): [] for b in buckets}
    cutoff = today - timedelta(days=days - 1)
    for est in estimates:
        if not est.created_at or est.created_at < cutoff:
            continue
        label = _day_label(_day_floor(est.created_at))
        if label in estimates_by_day:
            estimates_by_day[label].append(est)

    time_saved = []
    approval_rate = []
    average_estimate = []
    vendor_usage_series = []
    cost_savings = []
    satisfaction = []  # placeholder until customer feedback is tracked
    for b in buckets:
        label = _day_label(b)
        day_ests = estimates_by_day[label]

        approved_day = [e for e in day_ests if str(e.status) in ("approved", EstimateStatus.APPROVED.value)]
        decided_day = [
            e for e in day_ests
            if str(e.status) in ("approved", "declined", EstimateStatus.APPROVED.value, EstimateStatus.DECLINED.value)
        ]

        time_saved.append({"label": label, "value": len(approved_day) * TIME_SAVED_PER_ESTIMATE_MIN})
        approval_rate.append({
            "label": label,
            "value": round((len(approved_day) / len(decided_day)) * 100) if decided_day else 0,
        })
        avg_total = (
            round(sum(float(e.total or 0) for e in day_ests) / len(day_ests), 2) if day_ests else 0
        )
        average_estimate.append({"label": label, "value": avg_total})

        # Vendor usage trend — pick the lead vendor (most parts that day) share.
        day_vendor_counter: Counter = Counter()
        for est in day_ests:
            for item in (est.items or []):
                if (item.item_type or "").lower() == "part" and item.vendor_name:
                    day_vendor_counter[item.vendor_name] += 1
        total_day_parts = sum(day_vendor_counter.values())
        lead_pct = 0
        if total_day_parts:
            lead_pct = round((day_vendor_counter.most_common(1)[0][1] / total_day_parts) * 100)
        vendor_usage_series.append({"label": label, "value": lead_pct})

        # Cost savings — sum of estimate "saved" markers (not yet stored per
        # estimate). Until we persist that, derive from approved total *
        # average markup. Returns 0 for now to keep the chart honest.
        cost_savings.append({"label": label, "value": 0})

        # Satisfaction — no feedback loop yet; null so the UI can hide it.
        satisfaction.append({"label": label, "value": None})

    return {
        "range_days": days,
        "time_saved_min": time_saved,
        "approval_rate_pct": approval_rate,
        "average_estimate_usd": average_estimate,
        "vendor_usage_pct": vendor_usage_series,
        "cost_savings_usd": cost_savings,
        "customer_satisfaction_pct": satisfaction,
    }
