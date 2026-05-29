"""Estimaro ALLDATA Benchmark Runner

Runs the full pipeline (Hermes -> NHTSA -> ALLDATA agent) over a fixed list
of (VIN, complaint) test cases and writes a JSON report.

Between tests it navigates the live Chrome to the ALLDATA vehicle-selector
page so each run starts from a clean state.

Usage:
    python benchmark.py            # all cases
    python benchmark.py 1 2 3      # subset by index (1-based)
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime

from loguru import logger

from config import settings
from core.hermes_client import HermesClient
from core.browser import ChromeDebugBrowser
from services.nhtsa_service import decode_vin
from agents.alldata_agent import lookup_labor_time, ALLDATA_HOME
from models.job_spec import JobSpec


# --------------------------------------------------------------- test cases
TEST_CASES = [
    {  # 1 — baseline (known working)
        "vin": "2HGFC2F59JH123456",
        "complaint": "2018 Honda Civic making grinding noise from front when braking at low speeds",
        "expected_subsystem": "front brakes",
    },
    {  # 2
        "vin": "4T1G11AK4LU123456",
        "complaint": "2020 Toyota Camry oil leak from underneath, low oil pressure light came on",
        "expected_subsystem": "engine oil",
    },
    {  # 3
        "vin": "1FTFW1E51KFA12345",
        "complaint": "2019 Ford F-150 transmission slipping when shifting from 2nd to 3rd gear",
        "expected_subsystem": "automatic transmission",
    },
    {  # 4
        "vin": "WBA8E9G5XHN123456",
        "complaint": "2017 BMW 3 Series squealing noise from rear brakes when stopping",
        "expected_subsystem": "rear brakes",
    },
    {  # 5
        "vin": "55SWF8DB7MU123456",
        "complaint": "2021 Mercedes-Benz C-Class clunking sound from front suspension over bumps",
        "expected_subsystem": "front strut",
    },
    {  # 6
        "vin": "WAUANAF44JN123456",
        "complaint": "2018 Audi A4 coolant leaking under hood, engine running hot",
        "expected_subsystem": "cooling system",
    },
    {  # 7
        "vin": "1G1ZB5ST6GF123456",
        "complaint": "2016 Chevrolet Malibu starter motor clicking, engine won't crank",
        "expected_subsystem": "starting system",
    },
    {  # 8
        "vin": "5J6RW2H59NL123456",
        "complaint": "2022 Honda CR-V battery dead repeatedly, needs replacement",
        "expected_subsystem": "battery",
    },
    {  # 9
        "vin": "5YFBURHE3FP123456",
        "complaint": "2015 Toyota Corolla engine misfiring at idle, spark plugs need replacement",
        "expected_subsystem": "spark plugs",
    },
    {  # 10
        "vin": "KMHD84LF5KU123456",
        "complaint": "2019 Hyundai Elantra front brake rotors warped, pulsing when braking",
        "expected_subsystem": "front rotors",
    },
]


# ----------------------------------------------------------------- helpers
SELECT_VEHICLE_URL = "https://my.alldata.com/repair/#/select-vehicle"


async def reset_to_vehicle_selector():
    """Navigate the live ALLDATA tab back to vehicle selector."""
    async with ChromeDebugBrowser() as browser:
        page = await browser.open_or_focus(SELECT_VEHICLE_URL)
        try:
            await page.goto(SELECT_VEHICLE_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"reset navigation failed: {e}")


async def run_one(idx: int, case: dict, hermes: HermesClient) -> dict:
    label = f"[{idx + 1}/{len(TEST_CASES)}]"
    logger.info(f"\n{'='*70}\n{label}  VIN={case['vin']}  -- {case['complaint'][:60]}\n{'='*70}")

    t0 = time.time()
    record = {
        "idx": idx + 1,
        "vin": case["vin"],
        "complaint": case["complaint"],
        "expected_subsystem": case["expected_subsystem"],
        "status": "running",
    }

    try:
        # Stage 1: Hermes
        job_dict = hermes.parse_job_spec(case["complaint"], case["vin"])
        job = JobSpec(**job_dict)
        record["hermes"] = {
            "system": job.system,
            "subsystem": job.subsystem,
            "symptom": job.symptom[:120],
        }

        # Stage 2: NHTSA
        vehicle = await decode_vin(case["vin"])
        record["vehicle"] = {
            "year": vehicle.year, "make": vehicle.make, "model": vehicle.model,
            "trim": vehicle.trim, "engine": vehicle.engine,
        }
        logger.info(f"  decoded: {vehicle.year} {vehicle.make} {vehicle.model} {vehicle.trim or ''}")

        # Stage 3: reset Chrome
        await reset_to_vehicle_selector()

        # Stage 4: ALLDATA agent
        labor, meta = await lookup_labor_time(job, vehicle, max_steps=25)

        elapsed = time.time() - t0
        record["elapsed_sec"] = round(elapsed, 1)
        record["steps_taken"] = meta.get("agent_run", {}).get("steps_taken", 0) if isinstance(meta, dict) else 0

        if labor:
            record["status"] = "success"
            record["labor"] = labor.model_dump()
            record["parts"] = meta.get("parts", [])
            record["verification"] = meta.get("verification", {})
            record["extraction_confidence"] = meta.get("extraction_confidence", 0.0)
            record["section_path"] = meta.get("section_path", "")
            logger.info(
                f"  OK  operation='{labor.operation}'  hours={labor.hours}  "
                f"parts={len(record['parts'])}  elapsed={elapsed:.1f}s  steps={record['steps_taken']}"
            )
        else:
            record["status"] = "no_extract"
            record["agent_steps"] = meta.get("steps_taken") if isinstance(meta, dict) else None
            logger.warning(f"  NO EXTRACTION  elapsed={elapsed:.1f}s")

    except Exception as e:
        record["status"] = "error"
        record["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        record["elapsed_sec"] = round(time.time() - t0, 1)
        logger.error(f"  ERROR {record['error']}")

    return record


# ------------------------------------------------------------------- main
async def main(selected_indices: list[int] | None = None):
    hermes = HermesClient()
    cases = TEST_CASES
    if selected_indices:
        cases = [TEST_CASES[i - 1] for i in selected_indices if 1 <= i <= len(TEST_CASES)]

    records = []
    for i, case in enumerate(cases):
        rec = await run_one(i, case, hermes)
        records.append(rec)
        # short pause to let ALLDATA settle
        await asyncio.sleep(6)

    # Write report
    out_dir = Path(settings.SCREENSHOT_DIR).parent / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"benchmark_{stamp}.json"
    out_file.write_text(json.dumps(records, indent=2, default=str))
    logger.info(f"\nReport: {out_file}")

    # Print summary table
    print("\n" + "=" * 110)
    print(f"{'#':>2}  {'VIN':<18}  {'Vehicle':<35}  {'Status':<10}  {'Operation':<24}  {'hr':>5}  {'parts':>5}  {'t(s)':>5}")
    print("-" * 110)
    succ = 0
    for r in records:
        veh = r.get("vehicle", {})
        veh_str = f"{veh.get('year','?')} {veh.get('make','?')} {veh.get('model','?')}"[:35]
        labor = r.get("labor", {}) or {}
        op = (labor.get("operation") or "—")[:24]
        hr = labor.get("hours")
        hr_str = f"{hr}" if hr is not None else "—"
        nparts = len(r.get("parts", []))
        t = r.get("elapsed_sec", 0)
        print(f"{r['idx']:>2}  {r['vin']:<18}  {veh_str:<35}  {r['status']:<10}  {op:<24}  {hr_str:>5}  {nparts:>5}  {t:>5}")
        if r["status"] == "success":
            succ += 1
    print("-" * 110)
    print(f"Success: {succ}/{len(records)}  ({100*succ/len(records):.0f}%)")
    print("=" * 110)


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    asyncio.run(main(args or None))
