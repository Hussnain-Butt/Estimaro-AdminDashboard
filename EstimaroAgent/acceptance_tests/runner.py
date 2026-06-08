"""ALLDATA acceptance test runner — task #17.

Submits each test case via the same /api/v1/auto-generate/jobs endpoint
the FE uses, polls for completion, validates the result against the
case's `expected` block, and prints a pass/fail summary plus a JSON
report. Same execution path as production — no test-only shortcuts.

Usage from the VPS (worker user):

    cd /home/estimaro/Estimaro-AdminDashboard/EstimaroAgent
    PYTHONPATH=. venv/bin/python -m acceptance_tests.runner [case_name ...]

When no case names are given, runs ALL declared cases.

Graduation rule (Sergio June 6 spirit): >=80% case pass rate over THREE
consecutive runs of the full suite. Use `--repeat 3` to do that in one
invocation; runs are sequential so a cache HIT on run 2/3 is expected
and surfaces a faster wall-clock — itself a validation of task #16.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
from loguru import logger

from acceptance_tests.cases import TEST_CASES, case_by_name


BACKEND_URL = os.environ.get(
    "BACKEND_URL", "https://backend-production-9f132.up.railway.app"
).rstrip("/")
POLL_INTERVAL = float(os.environ.get("ACCEPTANCE_POLL_SEC", "10"))
POLL_TIMEOUT = int(os.environ.get("ACCEPTANCE_TIMEOUT", "900"))  # 15 min


# ---------------------------------------------------------------------------


def _check(label: str, condition: bool, detail: str = "") -> dict:
    return {
        "label": label,
        "passed": bool(condition),
        "detail": detail if not condition else "",
    }


def validate_result(case: dict, result: dict) -> list[dict]:
    """Apply every expectation in the case to the result; return a list of
    {label, passed, detail} dicts. Failures carry the actual observed
    value in `detail` for the report."""
    e = case.get("expected") or {}
    checks: list[dict] = []

    # --- service-type / skeleton ---------------------------------------
    sk = result.get("serviceSkeleton") or {}
    if e.get("service_type"):
        checks.append(_check(
            "service_type matches",
            sk.get("service_type") == e["service_type"],
            f"got {sk.get('service_type')!r}, expected {e['service_type']!r}",
        ))
    if e.get("skeleton_coverage_min_pct") is not None:
        cov = float(sk.get("coverage_pct") or 0)
        checks.append(_check(
            f"skeleton coverage >= {e['skeleton_coverage_min_pct']}%",
            cov >= float(e["skeleton_coverage_min_pct"]),
            f"got {cov}%",
        ))
    if e.get("skeleton_must_include_keys"):
        comp_keys = {
            (c.get("key") or "").lower()
            for c in (sk.get("components") or [])
        }
        for required in e["skeleton_must_include_keys"]:
            checks.append(_check(
                f"skeleton has component '{required}'",
                required.lower() in comp_keys,
                f"components present: {sorted(comp_keys)}",
            ))

    # --- labor row ------------------------------------------------------
    labor = (result.get("laborItems") or [{}])[0]
    op = (labor.get("description") or "").lower()
    if e.get("labor_operation_contains"):
        wants = e["labor_operation_contains"]
        if isinstance(wants, str):
            wants = [wants]
        hit = any(w.lower() in op for w in wants)
        checks.append(_check(
            f"labor operation contains one of {wants}",
            hit,
            f"got {op!r}",
        ))
    try:
        hrs = float(labor.get("hours") or 0)
    except (TypeError, ValueError):
        hrs = 0.0
    if e.get("labor_hours_min") is not None:
        checks.append(_check(
            f"labor hours >= {e['labor_hours_min']}",
            hrs >= float(e["labor_hours_min"]),
            f"got {hrs}h",
        ))
    if e.get("labor_hours_max") is not None:
        checks.append(_check(
            f"labor hours <= {e['labor_hours_max']}",
            hrs <= float(e["labor_hours_max"]),
            f"got {hrs}h",
        ))

    # --- estimate total --------------------------------------------------
    breakdown = result.get("breakdown") or {}
    try:
        total = float(breakdown.get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if e.get("total_min") is not None:
        checks.append(_check(
            f"total >= ${e['total_min']}",
            total >= float(e["total_min"]),
            f"got ${total:.2f}",
        ))
    if e.get("total_max") is not None:
        checks.append(_check(
            f"total <= ${e['total_max']}",
            total <= float(e["total_max"]),
            f"got ${total:.2f}",
        ))

    # --- confidence tier -------------------------------------------------
    if e.get("confidence_tier_allowed"):
        conf = result.get("confidence") or {}
        tier = (conf.get("tier") or "").lower()
        checks.append(_check(
            f"confidence tier in {e['confidence_tier_allowed']}",
            tier in [t.lower() for t in e["confidence_tier_allowed"]],
            f"got {tier!r}",
        ))

    # --- vendor coverage -------------------------------------------------
    if e.get("vendor_quotes_min") is not None:
        n_priced = sum(
            1 for q in (result.get("vendorQuotes") or [])
            if q.get("found") and (q.get("price") or 0) > 0
        )
        checks.append(_check(
            f"vendor quotes returned >= {e['vendor_quotes_min']}",
            n_priced >= int(e["vendor_quotes_min"]),
            f"got {n_priced} priced quotes",
        ))

    # --- auto-added components -------------------------------------------
    if e.get("auto_added_must_include"):
        auto_added_names = {
            (p.get("description") or "").lower()
            for p in (result.get("partsItems") or [])
            if p.get("auto_added")
        }
        for needed in e["auto_added_must_include"]:
            checks.append(_check(
                f"auto-added line '{needed}' present",
                needed.lower() in auto_added_names,
                f"auto-added: {sorted(auto_added_names)}",
            ))

    return checks


# ---------------------------------------------------------------------------


async def submit_case(client: httpx.AsyncClient, case: dict) -> str | None:
    """POST the case to /auto-generate/jobs. Return job_id or None on error."""
    try:
        r = await client.post(
            f"{BACKEND_URL}/api/v1/auto-generate/jobs",
            json=case["input"],
            timeout=30,
        )
        if r.status_code >= 400:
            logger.error(f"submit failed http={r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        return data.get("job_id")
    except Exception as e:
        logger.error(f"submit error: {e}")
        return None


async def poll_until_done(client: httpx.AsyncClient, job_id: str) -> dict:
    """Poll the job until status is success/failed or timeout. Return the
    full job dict."""
    deadline = time.time() + POLL_TIMEOUT
    last_progress = None
    while time.time() < deadline:
        try:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/auto-generate/jobs/{job_id}",
                timeout=20,
            )
            if r.status_code >= 400:
                logger.warning(f"poll http {r.status_code}: {r.text[:120]}")
                await asyncio.sleep(POLL_INTERVAL)
                continue
            j = r.json()
            status = j.get("status")
            prog = j.get("progress")
            if prog != last_progress:
                logger.info(f"  [{job_id[:12]}] {status}: {prog}")
                last_progress = prog
            if status in ("succeeded", "completed", "success"):
                return j
            if status in ("failed", "error"):
                return j
        except Exception as e:
            logger.warning(f"poll error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
    return {"status": "timeout", "job_id": job_id, "error": f"poll timeout after {POLL_TIMEOUT}s"}


async def run_one_case(client: httpx.AsyncClient, case: dict) -> dict:
    """Run a single acceptance case end-to-end. Return a per-case report dict."""
    name = case.get("name", "(unnamed)")
    print(f"\n{'=' * 70}\n[{name}] Submitting...")
    t0 = time.time()
    job_id = await submit_case(client, case)
    if not job_id:
        return {"name": name, "status": "submit_failed", "checks": [], "elapsed_sec": 0,
                "pass_rate": 0.0, "passed_overall": False}
    print(f"  job_id: {job_id}")
    job = await poll_until_done(client, job_id)
    elapsed = round(time.time() - t0, 1)
    status = job.get("status")
    if status not in ("succeeded", "completed", "success"):
        return {
            "name": name, "status": status or "unknown",
            "elapsed_sec": elapsed,
            "error": job.get("error", "(no error message)"),
            "checks": [], "pass_rate": 0.0, "passed_overall": False,
        }
    result = job.get("result") or {}
    checks = validate_result(case, result)
    n_pass = sum(1 for c in checks if c["passed"])
    n_total = len(checks)
    pass_rate = (n_pass / n_total) if n_total else 0.0
    passed_overall = pass_rate >= 1.0  # ALL checks must pass for case to pass

    # Print summary
    print(f"  elapsed: {elapsed}s   checks: {n_pass}/{n_total} passed")
    for c in checks:
        glyph = "✓" if c["passed"] else "✗"
        print(f"    {glyph} {c['label']}{(' — ' + c['detail']) if c['detail'] else ''}")

    return {
        "name": name,
        "status": "ok",
        "job_id": job_id,
        "elapsed_sec": elapsed,
        "result_summary": {
            "labor_op": (result.get("laborItems") or [{}])[0].get("description"),
            "labor_hrs": (result.get("laborItems") or [{}])[0].get("hours"),
            "total": (result.get("breakdown") or {}).get("total"),
            "tier": (result.get("confidence") or {}).get("tier"),
            "coverage_pct": (result.get("serviceSkeleton") or {}).get("coverage_pct"),
            "vendor_priced": sum(
                1 for q in (result.get("vendorQuotes") or [])
                if q.get("found") and (q.get("price") or 0) > 0
            ),
        },
        "checks": checks,
        "pass_rate": round(pass_rate, 3),
        "passed_overall": passed_overall,
    }


async def run_suite(case_names: list[str] | None = None, repeat: int = 1) -> dict:
    """Run the requested cases `repeat` times; return summary report."""
    cases = TEST_CASES if not case_names else [
        c for n in case_names for c in [case_by_name(n)] if c
    ]
    if case_names and len(cases) != len(case_names):
        missing = set(case_names) - {c["name"] for c in cases}
        print(f"Unknown case names: {missing}")

    all_runs: list[list[dict]] = []
    async with httpx.AsyncClient() as client:
        for r in range(repeat):
            print(f"\n{'#' * 70}\n# RUN {r+1}/{repeat}\n{'#' * 70}")
            run_reports = []
            for case in cases:
                report = await run_one_case(client, case)
                run_reports.append(report)
            all_runs.append(run_reports)

    # Roll-up
    print(f"\n{'=' * 70}\nSUITE SUMMARY ({len(cases)} cases × {repeat} runs)\n{'=' * 70}")
    per_run_pass_rate = []
    for i, run in enumerate(all_runs):
        n_pass = sum(1 for r in run if r["passed_overall"])
        rate = n_pass / len(run) if run else 0
        per_run_pass_rate.append(rate)
        avg_elapsed = sum(r.get("elapsed_sec", 0) for r in run) / len(run) if run else 0
        print(f"  Run {i+1}: {n_pass}/{len(run)} cases passed ({rate*100:.0f}%)  "
              f"avg {avg_elapsed:.1f}s/case")

    overall_pass_rate = sum(per_run_pass_rate) / len(per_run_pass_rate) if per_run_pass_rate else 0
    graduation_threshold = 0.80
    graduates = overall_pass_rate >= graduation_threshold

    print(f"\n  Overall pass rate: {overall_pass_rate*100:.1f}%")
    print(f"  Graduation threshold: {graduation_threshold*100:.0f}%")
    print(f"  ALLDATA portal {'GRADUATES' if graduates else 'NEEDS MORE WORK'} →"
          f" {'ready to move to next portal' if graduates else 'fix failing cases first'}")

    return {
        "runs": all_runs,
        "per_run_pass_rate": per_run_pass_rate,
        "overall_pass_rate": overall_pass_rate,
        "graduation_threshold": graduation_threshold,
        "graduated": graduates,
    }


def main():
    parser = argparse.ArgumentParser(description="ALLDATA acceptance suite")
    parser.add_argument("case_names", nargs="*",
                        help="Specific case names to run; omit for all.")
    parser.add_argument("--repeat", type=int, default=1,
                        help="How many times to run the suite (default 1).")
    parser.add_argument("--report-file", type=str, default=None,
                        help="Optional path to write JSON report.")
    args = parser.parse_args()

    summary = asyncio.run(run_suite(args.case_names or None, args.repeat))

    if args.report_file:
        with open(args.report_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nJSON report: {args.report_file}")

    # Exit code: 0 if graduated, 1 if not (CI-friendly)
    sys.exit(0 if summary["graduated"] else 1)


if __name__ == "__main__":
    main()
