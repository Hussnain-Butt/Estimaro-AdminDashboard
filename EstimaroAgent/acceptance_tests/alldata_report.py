"""Standalone ALLDATA-only validation report.

Bypasses the worker queue + the vendor pricing pipeline. Calls the
ALLDATA agent directly so the output contains ONLY ALLDATA-sourced
data: labor row, Parts-table OEM parts, Repair-Procedure renew /
replace items, and the skeleton expectation list — with NO vendor
quotes / no markup / no totals to muddy the review.

Use case: send the output to the client so they can confirm whether
ALLDATA's view of the job (what to replace, how long it takes) matches
what they'd add manually. Removes vendor-pricing variance from the
accuracy question.

Usage from the VPS:

    cd /home/estimaro/Estimaro-AdminDashboard/EstimaroAgent
    PYTHONPATH=. venv/bin/python -m acceptance_tests.alldata_report \\
        YV1SZ58D621078311 "Front brake service" \\
        --out /tmp/alldata_report.md

    # Force a fresh ALLDATA agent run (ignore cache):
    PYTHONPATH=. venv/bin/python -m acceptance_tests.alldata_report \\
        YV1SZ58D621078311 "Front brake service" --no-cache
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from io import StringIO

from agents.alldata_agent import lookup_labor_time
from core.hermes_client import HermesClient
from models.job_spec import JobSpec
from services.nhtsa_service import decode_vin
from services.service_skeleton import skeleton_for_job
from services.result_cache import get_cached_result, store_result


def _fmt_money(n) -> str:
    try:
        return f"${float(n):.2f}"
    except (TypeError, ValueError):
        return "$?"


async def build_report(vin: str, complaint: str, use_cache: bool = True) -> str:
    out = StringIO()

    def w(line: str = "") -> None:
        out.write(line + "\n")

    w(f"# ALLDATA-only validation report")
    w()
    w(f"**VIN:** `{vin}`")
    w(f"**Customer complaint:** {complaint}")
    w(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w()
    w("> This report shows ONLY what ALLDATA returned — labor row, parts table,")
    w("> repair-procedure renew/replace items, and what the service skeleton")
    w("> expected. Vendor pricing (Worldpac / SSF / PartsLink24) is intentionally")
    w("> excluded so the question 'are ALLDATA's values right?' isn't entangled")
    w("> with vendor-coverage variance.")
    w()
    w("---")
    w()

    # ---- Hermes intent parse + NHTSA VIN decode ----
    t0 = time.time()
    hermes = HermesClient()
    job_dict = hermes.parse_job_spec(complaint, vin)
    spec = JobSpec(**job_dict)
    vehicle = await decode_vin(vin)
    decode_sec = round(time.time() - t0, 1)

    w("## Vehicle (NHTSA decoded)")
    w()
    w(f"- **Year:** {vehicle.year}")
    w(f"- **Make:** {vehicle.make}")
    w(f"- **Model:** {vehicle.model}")
    w(f"- **Trim:** {vehicle.trim or '—'}")
    w(f"- **Engine:** {vehicle.engine or '—'}")
    w(f"- **VIN:** `{vehicle.vin}`")
    w(f"- _(decoded in {decode_sec}s)_")
    w()

    # ---- Service-type classification + skeleton ----
    skeleton = skeleton_for_job(spec)

    w("## Service classification (Hermes + skeleton)")
    w()
    w(f"- **System:** `{spec.system}`")
    w(f"- **Subsystem:** `{spec.subsystem}`")
    w(f"- **Symptom:** {spec.symptom}")
    w(f"- **Keywords:** {', '.join(spec.keywords) or '—'}")
    if skeleton:
        w(f"- **Service type:** `{skeleton['service_type']}` — {skeleton['display_name']}")
        rng = skeleton.get("expected_estimate_range") or []
        if len(rng) == 2:
            w(f"- **Industry estimate range:** ${rng[0]}-${rng[1]}")
        if skeleton.get("labor_preferred"):
            w(f"- **Preferred labor row:** `{skeleton['labor_preferred']}` "
              f"(default {skeleton.get('labor_default_hours', '?')}h)")
    else:
        w(f"- **Service type:** _no skeleton match — generic job_")
    w()

    # ---- ALLDATA agent run ----
    t1 = time.time()
    cache_status = "skipped"
    labor, meta = None, None
    service_type_key = skeleton["service_type"] if skeleton else None

    if use_cache:
        cached = get_cached_result(vin, service_type_key, complaint)
        if cached:
            try:
                from models.job_spec import LaborResult
                lr = cached.get("labor")
                if lr:
                    labor = LaborResult(**lr)
                meta = cached.get("meta") or {}
                cache_status = "HIT"
            except Exception:
                cache_status = "rehydrate_failed"

    if labor is None:
        cache_status = "MISS (running live)" if use_cache else "skipped (live forced)"
        w(f"## ALLDATA agent — _running live, may take 4-7 min_")
        w()
        labor, meta = await lookup_labor_time(
            spec, vehicle, max_steps=15, service_skeleton=skeleton
        )
        # Store for future runs
        if labor and not (meta or {}).get("fail_reason"):
            store_result(vin, service_type_key, complaint,
                         {"labor": labor.model_dump(), "meta": meta})

    alldata_sec = round(time.time() - t1, 1)

    if not labor:
        w(f"❌ **ALLDATA extraction failed**")
        w()
        w(f"- **Reason:** `{(meta or {}).get('fail_reason') or 'unknown'}`")
        w(f"- **Elapsed:** {alldata_sec}s")
        return out.getvalue()

    # ---- Labor row ----
    w(f"## Labor row extracted")
    w(f"_(source: ALLDATA Parts & Labor article)_")
    w()
    w(f"- **Operation:** **{labor.operation}**")
    w(f"- **Hours:** **{labor.hours}**")
    vm = labor.vehicle_match or {}
    if vm.get("skill"):
        w(f"- **Skill:** {vm['skill']}")
    if vm.get("reported"):
        w(f"- **ALLDATA matched as:** {vm['reported']}")
    if meta.get("section_path"):
        w(f"- **Catalogue path:** `{meta['section_path']}`")
    w(f"- **Cache:** {cache_status}, elapsed {alldata_sec}s")
    w()

    # Determinism + verification quality signals
    det = meta.get("determinism") or {}
    ver = meta.get("verification") or {}
    w(f"### Quality signals")
    w()
    w(f"- **Determinism:** `{det.get('status')}`"
      + (f" (preferred row `{det['preferred']}`)" if det.get("preferred") else ""))
    w(f"- **Extraction confidence:** {meta.get('extraction_confidence', 0):.2f}")
    w(f"- **Hermes verification:** match=`{ver.get('match')}`, "
      f"confidence={ver.get('confidence', 0):.2f}")
    if ver.get("reason"):
        w(f"  > _{ver['reason'][:200]}_")
    w()

    # ---- Parts table (ALLDATA) ----
    parts = meta.get("parts") or []
    w(f"## Parts listed by ALLDATA's Parts table ({len(parts)} item{'s' if len(parts) != 1 else ''})")
    w()
    if parts:
        w("| # | Name | OEM Part # | Qty | ALLDATA List Price |")
        w("|---|------|------------|-----|--------------------|")
        for i, p in enumerate(parts, 1):
            w(f"| {i} | {p.get('name', '?')} | `{p.get('oem_number', '?')}` "
              f"| {p.get('qty', 1)} | {_fmt_money(p.get('price'))} |")
    else:
        w("_None — ALLDATA's Parts table was empty for this article._")
    w()

    # ---- Repair Procedure scan ----
    rp = meta.get("repair_procedure") or {}
    rp_items = rp.get("items") or []
    rp_status = rp.get("scan_status")
    w(f"## ALLDATA Repair Procedure — renew / replace / torque-to-yield items")
    w(f"_(scan status: `{rp_status}`)_")
    w()
    if rp_items:
        w("| Component | Action | Qty | Context |")
        w("|-----------|--------|-----|---------|")
        for it in rp_items:
            ctx = (it.get("contexts") or [""])[0][:120].replace("|", "/")
            w(f"| {it.get('component_phrase', '?')} | `{it.get('action', '?')}` "
              f"| {it.get('quantity') or '—'} | _{ctx}_ |")
    else:
        w("_None — the repair article didn't expose replacement keywords on this scan._")
    w()

    # ---- Skeleton expected vs found ----
    w(f"## Skeleton — what the service \"always\" includes")
    w(f"_(derived from Sergio's verbatim description of this service type)_")
    w()
    if not skeleton:
        w("_No skeleton match for this job — generic processing._")
    else:
        components = list(skeleton.get("components", [])) + list(skeleton.get("addons", []))
        parts_names_lc = [(p.get('name') or '').lower() for p in parts]
        rp_keys = {(it.get('component_key') or '').lower() for it in rp_items}
        rp_phrases = [(it.get('component_phrase') or '').lower() for it in rp_items]

        # Token-overlap matcher — "Front Brake Pad Set" should match
        # ALLDATA's "15\" Wheels Front Pads" because both share the
        # tokens 'front' + 'pads'. Strict substring missed this.
        def _tok(s: str) -> set:
            return {t for t in (s or "").lower().replace('"', '').split()
                    if len(t) > 2 and t not in {"the", "and", "for", "set"}}

        def _matches(component_name: str, candidate_terms: list, target: str) -> bool:
            t = (target or "").lower()
            if not t:
                return False
            ct = _tok(component_name)
            for cand in candidate_terms:
                cand_l = (cand or "").lower()
                if not cand_l:
                    continue
                if cand_l in t or t in cand_l:
                    return True
                cand_t = _tok(cand)
                if cand_t and len(cand_t & _tok(target)) >= max(1, len(cand_t) // 2):
                    return True
            # also try the display name itself
            target_t = _tok(target)
            if ct and target_t and len(ct & target_t) >= max(1, len(ct) // 2):
                return True
            return False

        w("| Component | Qty | Kind | Source | Notes |")
        w("|-----------|-----|------|--------|-------|")
        for c in components:
            cname = c.get('display_name', '?')
            ckey = (c.get('key') or '').lower()
            cqty = c.get('default_qty', 1)
            ckind = c.get('kind', 'part')
            reason = (c.get('reason') or '')[:80]
            cand_terms = ([cname]
                          + list(c.get('vendor_search_terms') or [])
                          + list(c.get('alldata_keywords') or []))

            in_parts = any(_matches(cname, cand_terms, pn) for pn in parts_names_lc if pn)
            in_rp = (any(ckey and (rk in ckey or ckey in rk) for rk in rp_keys)
                     or any(_matches(cname, cand_terms, rp) for rp in rp_phrases if rp))

            if in_parts:
                status = "✅ Parts table"
            elif in_rp:
                status = "✅ Repair Procedure"
            elif c.get('always_required', True):
                status = "⚠️ MISSING"
            else:
                status = "○ Optional"
            w(f"| **{cname}** | {cqty} | {ckind} | {status} | _{reason}_ |")
    w()

    # ---- Operator action prompt ----
    w("---")
    w()
    w("## For the client to confirm")
    w()
    w("Please review and reply with any of the following:")
    w()
    w("1. **Labor row** — is the operation `{op}` and the time `{hrs}h` what you'd quote for this job?".format(
        op=labor.operation, hrs=labor.hours,
    ))
    w("2. **Parts table** — are the OEM part numbers above the right ones, "
      "or are they the wrong variant / wrong axle / wrong trim?")
    w("3. **Repair Procedure items** — does the renew/replace list cover everything "
      "you'd actually swap, or is something missing?")
    w("4. **Skeleton expectations** — are the ✅/⚠️ marks against the right items? "
      "Should we ADD or REMOVE any default component for this service type?")
    w()
    w("Anything marked ⚠️ MISSING means ALLDATA didn't list it on this article — "
      "we add it manually today. If a service type should always include something "
      "we missed, tell us and we update the skeleton permanently.")
    w()

    return out.getvalue()


async def amain():
    parser = argparse.ArgumentParser(description="ALLDATA-only validation report")
    parser.add_argument("vin", help="VIN to look up")
    parser.add_argument("complaint", nargs="+",
                        help="Customer complaint (will be joined)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip the result cache, force live ALLDATA run")
    parser.add_argument("--out", default=None,
                        help="Write report markdown to this path "
                             "(default: print to stdout only)")
    args = parser.parse_args()

    complaint = " ".join(args.complaint)
    report = await build_report(args.vin, complaint, use_cache=not args.no_cache)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[written to {args.out}]", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(amain())
