"""Historical RO corpus — Phase B.

Sergio has ~30k completed (Paid/POSTED) Tekmetric ROs, each one ground-truth
(he built it, the customer paid). This module turns the raw scrape from
`scrapers.tekmetric_job_board` into a queryable corpus so a NEW
(year, make, model, service_type) request can be answered from his OWN past
work before falling through to the 5–7 min ALLDATA vision agent.

Two halves:
  * PARSER — `parse_job()` / `normalize_record()` turn the scraper's raw
    per-job innerText blocks into structured labor + parts lines. Pure text,
    runs offline against saved JSON (no live session needed — iterate freely).
  * STORE — a small SQLite DB (`historical_corpus.db`) with one row per RO and
    the normalized jobs as JSON, plus a coarse vehicle/keyword index for
    nearest-neighbour lookup (`find_similar`).

Prices DRIFT, so the corpus is authoritative for LABOR (descriptions + hours)
and PART NUMBERS; live vendor pricing is refreshed at estimate time (see the
caveats in the project plan). Match on (year, make, model, service_type),
never VIN — VINs don't repeat across customers.

CLI:
  PYTHONPATH=. python -m services.historical_corpus ingest <scrape.json> [--db path]
  PYTHONPATH=. python -m services.historical_corpus stats [--db path]
  PYTHONPATH=. python -m services.historical_corpus find "2016 Volvo S60" "front brakes" [--db path]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Optional

DB_DEFAULT = str(Path(__file__).resolve().parent.parent / "data" / "historical_corpus.db")

_NUM = r"[\d,]+\.\d{2}"
_LABOR_HDR = "Labor\tTechnician\tHours\tRate\tTotal"
_PARTS_HDR = "Part\tQty\tCost\tRetail\tTotal"


def _f(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


# UI-button / status tokens that leak into the job text and must NOT be taken
# as a labor description or a part description.
_NOISE_LINES = {"assign", "otc", "add", "add category", "add labor", "batt",
                "comp", "ins", "mech", "eos", "cs", "approved", " no labor",
                "click here", "reassign labor & parts", "reorder jobs",
                "collapse all", "no labor added"}


def _is_noise(line: str) -> bool:
    c = line.strip().lower()
    return (not c) or c in _NOISE_LINES or c.startswith("approved")


def _looks_like_tech(line: str) -> bool:
    """Technician credit lines look like 'SERGIO  F.' or 'DANIEL G.' — short,
    capitalised, ending in an initial. We skip them when hunting for the labor
    description above a labor row."""
    c = line.strip()
    return bool(re.match(r"^[A-Z][A-Za-z]*\.?\s+[A-Z]\.$", c)) or (
        c.isupper() and len(c) <= 18 and " " in c
    )


def parse_job(text: str) -> dict:
    """Parse one job's raw innerText block into structured fields.

    Returns {name, category, approved_on, labor[], parts[], job_total}.
    Best-effort: anchored on Tekmetric's own table headers and the numeric
    triplets that terminate each labor/part row. Always survivable — unknown
    shapes yield empty lists rather than raising.
    """
    t = text.replace("\xa0", " ")
    lines = t.split("\n")
    name = lines[0].strip() if lines else ""

    appr = re.search(r"Approved on (.+?)(?:\n|$)", t)
    jt = re.search(rf"JOB TOTAL\s*\n\$({_NUM})", t)

    # Category code (MECH/COMP/INS/BATT/EOS/...) sits between the approval line
    # and the technician name, on its own short ALLCAPS line.
    category = None
    if appr:
        after = t[appr.end():appr.end() + 60].split("\n")
        for ln in after:
            c = ln.strip()
            if c and c.isupper() and 2 <= len(c) <= 6 and c.isalpha():
                category = c
                break

    li = t.find(_LABOR_HDR)
    pi = t.find(_PARTS_HDR)
    gp = t.find("GP%")
    labor_sec = t[li:(pi if pi != -1 else gp if gp != -1 else len(t))] if li != -1 else ""
    parts_sec = t[pi:(gp if gp != -1 else len(t))] if pi != -1 else ""

    labor: list[dict] = []
    lsl = labor_sec.split("\n")
    for idx, ln in enumerate(lsl):
        m = re.match(rf"\t?(\d+\.\d{{2}})\t\$({_NUM})\t\$({_NUM})\s*$", ln)
        if not m:
            continue
        desc = ""
        for k in range(idx - 1, -1, -1):
            c = lsl[k].strip()
            if _is_noise(c) or _looks_like_tech(c):
                continue
            desc = c
            break
        labor.append({"description": desc, "hours": _f(m.group(1)),
                      "rate": _f(m.group(2)), "total": _f(m.group(3))})

    parts: list[dict] = []
    psl = parts_sec.split("\n")
    for idx, ln in enumerate(psl):
        # A part row terminates with: <cost> \t $<retail> \t $<total>, and the
        # qty sits a line or two above. Description / part# / status / vendor
        # are the meaningful lines preceding the qty.
        m = re.match(rf"\t?\$({_NUM})\t\$({_NUM})\t\$({_NUM})\s*$", ln)
        if not m:
            continue
        # qty: nearest preceding bare integer line
        qty = None
        ptr = idx - 1
        while ptr >= 0:
            c = psl[ptr].strip()
            if re.fullmatch(r"\d+", c):
                qty = int(c)
                break
            ptr -= 1
            if idx - ptr > 5:
                break
        # collect the meaningful text lines above qty (desc, part#, status, vendor)
        block: list[str] = []
        k = ptr - 1
        while k >= 0 and len(block) < 5:
            c = psl[k].strip()
            # A "$" above this part's qty belongs to the PREVIOUS part's price
            # row — stop, or it leaks in as a bogus description/part number.
            if "$" in c:
                break
            if c and c != _PARTS_HDR and not re.fullmatch(r"\d+", c) and not _is_noise(c):
                block.append(c)
            if c == _PARTS_HDR or c.startswith("Part\t"):
                break
            k -= 1
        block.reverse()
        description = block[0] if block else ""
        part_number = block[1] if len(block) > 1 else None
        status = next((b for b in block if b in ("Inventory", "Needed", "Quoted")
                       or "Received" in b), None)
        vendor = block[-1] if len(block) > 2 else None
        # Skip pure-noise rows (no real description AND no part number) — they
        # add empty line items to the customer-facing estimate.
        if not description and not part_number:
            continue
        parts.append({"description": description, "part_number": part_number,
                      "status": status, "vendor": vendor, "qty": qty,
                      "cost": _f(m.group(1)), "retail": _f(m.group(2)),
                      "total": _f(m.group(3))})

    return {"name": name, "category": category,
            "approved_on": appr.group(1).strip() if appr else None,
            "labor": labor, "parts": parts,
            "job_total": _f(jt.group(1)) if jt else None}


def _clean_make_model(mm: Optional[str]) -> Optional[str]:
    """Strip a trailing status badge ('(PAID)' etc.) that leaks from paid-RO
    headings so vehicle matching stays clean."""
    if not mm:
        return mm
    return re.sub(r"\s*\((?:PAID|POSTED|COMPLETED|INVOICED?)\)\s*$", "", mm,
                  flags=re.IGNORECASE).strip()


# Make canonicalization. Old Tekmetric RO headings truncate ("MERCEDES-BEN"),
# abbreviate ("VW"), split two-word makes ("Land Rover" → make "Land"), and
# misspell ("CRHYSLER", "PORCHE", "BWM"). match_job's make gate compares
# _norm(make) by equality / substring, so these never match a clean query make
# ("mercedesben" ≠ "mercedesbenz", "vw" ⊄ "volkswagen", "land" ⊄ "landrover").
# (Pure case variants — AUDI vs Audi — already match because _norm lowercases.)
# Re-ingesting after a code change applies this to every row.
_MULTIWORD_MAKES = ("Mercedes-Benz", "Land Rover", "Rolls-Royce", "Alfa Romeo")
_MAKE_ALIASES = {  # normalized (lowercase-alnum) key → canonical display name
    "bmw": "BMW", "bwm": "BMW", "528bmw": "BMW",
    "mercedesbenz": "Mercedes-Benz", "mercedesben": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "mb": "Mercedes-Benz",
    "audi": "Audi",
    "volkswagen": "Volkswagen", "vw": "Volkswagen", "volkswagon": "Volkswagen",
    "golf": "Volkswagen",
    "porsche": "Porsche", "porche": "Porsche",
    "mini": "Mini", "toyota": "Toyota", "volvo": "Volvo", "honda": "Honda",
    "ford": "Ford", "nissan": "Nissan", "lexus": "Lexus",
    "landrover": "Land Rover", "land": "Land Rover", "rover": "Land Rover",
    "chevrolet": "Chevrolet", "chevy": "Chevrolet",
    "dodge": "Dodge", "acura": "Acura", "jeep": "Jeep", "saab": "Saab",
    "jaguar": "Jaguar", "subaru": "Subaru", "infiniti": "Infiniti",
    "hyundai": "Hyundai", "fiat": "Fiat", "cadillac": "Cadillac",
    "mazda": "Mazda", "mitsubishi": "Mitsubishi", "gmc": "GMC",
    "chrysler": "Chrysler", "crhysler": "Chrysler",
    "saturn": "Saturn", "smart": "Smart", "kia": "Kia", "buick": "Buick",
    "freightliner": "Freightliner", "pontiac": "Pontiac", "mercury": "Mercury",
    "maserati": "Maserati", "bentley": "Bentley",
    "alfa": "Alfa Romeo", "alfaromeo": "Alfa Romeo",
    "ram": "Ram", "plymouth": "Plymouth", "lincoln": "Lincoln",
    "tesla": "Tesla", "suzuki": "Suzuki", "oldsmobile": "Oldsmobile",
    "lotus": "Lotus", "isuzu": "Isuzu",
    "rollsroyce": "Rolls-Royce", "rolls": "Rolls-Royce",
    "mclaren": "McLaren", "hummer": "Hummer", "ferrari": "Ferrari",
    "komatsu": "Komatsu", "borgward": "Borgward",
}


def _canonical_make(raw: Optional[str]) -> Optional[str]:
    """Map a raw make token to a canonical display name. Unknown makes are
    title-cased (ALLCAPS/lowercase scrape artifacts) but otherwise preserved,
    so a new/rare make degrades gracefully instead of being silently dropped."""
    if not raw:
        return raw
    t = raw.strip()
    key = re.sub(r"[^a-z0-9]", "", t.lower())
    if not key:
        return None
    if key in _MAKE_ALIASES:
        return _MAKE_ALIASES[key]
    return t.title() if (t.isupper() or t.islower()) else t


def normalize_record(rec: dict) -> dict:
    """Turn a scraper record into a corpus row: header fields + parsed jobs."""
    jobs = [parse_job(j["text"]) for j in rec.get("jobs", []) if j.get("text")]
    # Drop empty inspection/$0 jobs from the service signal but keep the count.
    service_jobs = [j for j in jobs if j["labor"] or j["parts"]]
    return {
        "ro_number": rec.get("ro_number"),
        "internal_id": rec.get("internal_id"),
        "year": rec.get("year"),
        "make_model": _clean_make_model(rec.get("make_model")),
        "vin": rec.get("vin"),
        "date_posted": rec.get("date_posted"),
        "odometer": rec.get("odometer_out") or rec.get("odometer_in"),
        "labor_rate": rec.get("labor_rate"),
        "total": rec.get("total"),
        "labor_total": rec.get("labor_total"),
        "parts_total": rec.get("parts_total"),
        "jobs": jobs,
        "service_job_names": [j["name"] for j in service_jobs],
    }


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ros (
    ro_number    TEXT PRIMARY KEY,
    internal_id  TEXT,
    year         INTEGER,
    make         TEXT,
    model        TEXT,
    make_model   TEXT,
    vin          TEXT,
    date_posted  TEXT,
    odometer     TEXT,
    labor_rate   REAL,
    total        REAL,
    labor_total  REAL,
    parts_total  REAL,
    service_names TEXT,   -- space-joined job names for keyword matching
    jobs_json    TEXT,    -- normalized jobs[] (labor + parts lines)
    raw_json     TEXT     -- full scraper record for re-parsing later
);
CREATE INDEX IF NOT EXISTS idx_ros_vehicle ON ros (year, make, model);
"""


def _split_make_model(make_model: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not make_model:
        return None, None
    mm = make_model.strip()
    low = mm.lower()
    # Two-word makes must split AFTER the make — a naive first-space split turns
    # "Land Rover Range Rover Sport" into make="Land" (drops the match) with a
    # duplicated model. Match the canonical multi-word spelling first.
    for mk in _MULTIWORD_MAKES:
        mkl = mk.lower()
        if low == mkl or low.startswith(mkl + " "):
            return mk, (mm[len(mk):].strip() or None)
    parts = mm.split(" ", 1)
    return _canonical_make(parts[0]), (parts[1] if len(parts) > 1 else None)


def init_db(db_path: str = DB_DEFAULT) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


def ingest(records: list[dict], db_path: str = DB_DEFAULT) -> dict:
    conn = init_db(db_path)
    added = skipped = 0
    for rec in records:
        if rec.get("error") or not rec.get("ro_number"):
            skipped += 1
            continue
        norm = normalize_record(rec)
        make, model = _split_make_model(norm["make_model"])
        conn.execute(
            """INSERT OR REPLACE INTO ros (ro_number, internal_id, year, make,
               model, make_model, vin, date_posted, odometer, labor_rate, total,
               labor_total, parts_total, service_names, jobs_json, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (norm["ro_number"], norm["internal_id"], norm["year"], make, model,
             norm["make_model"], norm["vin"], norm["date_posted"], norm["odometer"],
             norm["labor_rate"], norm["total"], norm["labor_total"],
             norm["parts_total"], " | ".join(norm["service_job_names"]),
             json.dumps(norm["jobs"], ensure_ascii=False),
             json.dumps(rec, ensure_ascii=False)),
        )
        added += 1
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM ros").fetchone()[0]
    conn.close()
    return {"added": added, "skipped": skipped, "total_in_db": n}


def ingest_worker_result(vin: Optional[str], year: Optional[int],
                         make: Optional[str], model: Optional[str],
                         complaint: str, result: dict, *,
                         ro_number: Optional[str] = None,
                         db_path: str = DB_DEFAULT) -> Optional[str]:
    """Phase E — add an APPROVED estimate to the corpus so a repeat (vehicle,
    service) query matches it instantly (continuous learning).

    Call this ONLY for advisor-approved estimates (the Tekmetric-push path) —
    raw auto-builds must never enter the corpus, or an over-stuffed draft comes
    back as a high-confidence "historical match" on the next identical query.
    `ro_number`: the real Tekmetric RO# when known; falls back to a synthetic
    'EST-' key. No-op for empty / $0 estimates."""
    labor_items = result.get("laborItems") or []
    parts_items = result.get("partsItems") or []
    bd = result.get("breakdown") or {}
    try:
        total = float(bd.get("total") or 0)  # FE sends string totals
    except (TypeError, ValueError):
        total = 0.0
    if not labor_items or total <= 0:
        return None

    if not ro_number:
        vin8 = re.sub(r"[^A-Za-z0-9]", "", (vin or "anon"))[-8:].upper() or "ANON"
        svc_key = _norm(complaint)[:10] or "svc"
        ro_number = f"EST-{vin8}-{svc_key}"
    make = _canonical_make(make)  # keep approved-estimate makes canonical too
    make_model = " ".join(x for x in [make, model] if x).strip()
    jobs = [{
        "name": (complaint or "")[:100], "category": None, "approved_on": None,
        "labor": [{"description": l.get("description"), "hours": l.get("hours"),
                   "rate": l.get("rate"), "total": l.get("total")}
                  for l in labor_items],
        "parts": [{"description": p.get("description"), "part_number": p.get("partNumber"),
                   "status": None, "vendor": p.get("vendor"), "qty": p.get("quantity"),
                   "cost": p.get("cost"), "retail": p.get("list_price"),
                   "total": p.get("total")} for p in parts_items],
        "job_total": total,
    }]
    service_names = " | ".join([complaint or ""] +
                               [l.get("description") or "" for l in labor_items])
    conn = init_db(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO ros (ro_number, internal_id, year, make,
           model, make_model, vin, date_posted, odometer, labor_rate, total,
           labor_total, parts_total, service_names, jobs_json, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ro_number, None, int(year) if year else None, make, model, make_model,
         vin, None, None, None, total,
         _f(str(bd.get("laborTotal") or "")), _f(str(bd.get("partsTotal") or "")),
         service_names, json.dumps(jobs, ensure_ascii=False),
         json.dumps(result, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return ro_number


def stats(db_path: str = DB_DEFAULT) -> dict:
    conn = init_db(db_path)
    n = conn.execute("SELECT COUNT(*) FROM ros").fetchone()[0]
    makes = conn.execute(
        "SELECT make, COUNT(*) c FROM ros GROUP BY make ORDER BY c DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {"ros": n, "top_makes": makes}


# Words that carry no service signal — stripped before complaint/service
# keyword overlap so "my car needs the front brakes done please" reduces to
# {front, brakes}. We KEEP front/rear/left/right — they disambiguate parts.
_COMPLAINT_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "for", "my", "is", "it", "on",
    "in", "with", "please", "need", "needs", "car", "vehicle", "customer",
    "says", "i", "when", "has", "have", "had", "this", "that", "at", "be",
    "would", "like", "get", "getting", "do", "done", "doing", "want", "wants",
    "client", "their", "there", "its", "are", "was", "were", "im", "id",
    # 'service'/'repair' are too generic — nearly every job name contains one,
    # so they'd keep unrelated "oil service"/"ac repair" lines in a brake job.
    "service", "repair", "replace", "remove", "check", "inspect", "system",
}
# Light stemming so a complaint "brakes" matches a job "Brake Pad Set".
_SVC_SYNONYMS = {
    "brakes": "brake", "pads": "pad", "rotors": "rotor", "discs": "disc",
    "plugs": "plug", "filters": "filter", "fluids": "fluid", "tires": "tire",
    "shocks": "shock", "struts": "strut", "bearings": "bearing",
    "leaking": "leak", "leaks": "leak", "squeaking": "brake", "squealing": "brake",
    "grinding": "brake", "oil": "oil", "spark": "spark",
}


# Generic service-supply words. A part/labor line naming one of these is kept
# even if it doesn't match the complaint directly — they accompany most jobs
# (a brake job's cleaner, a service's gasket). Battery/bulb/tire are NOT here,
# so they get filtered out of an unrelated request.
# NOTE: 'kit' is deliberately NOT here — it names real parts ("Oil Filter Kit",
# "Timing Kit") and would leak an oil filter into a brake job. 'cleaning' /
# 'lubrication' keep the shop's cleaning-kit supply without that side effect.
_SUPPLY_WORDS = {"cleaner", "cleaning", "fluid", "grease", "lubricant", "lube",
                 "lubrication", "hardware", "clip", "shim", "sealer", "seal",
                 "gasket", "washer", "additive"}
# Largest year gap allowed between the query vehicle and a historical RO.
_MAX_YEAR_GAP = 8

# Concrete service nouns. A complaint must name at least one of these (or
# classify to a canonical type) before we attempt a historical match at all.
# "making noise" / "feels weird" are DIAGNOSIS requests — a past estimate for
# some other noise is exactly the wrong thing to show; let the live pipeline
# handle them.
_SERVICE_NOUNS = {
    "brake", "pad", "rotor", "disc", "caliper", "sensor", "oil", "filter",
    "plug", "spark", "shock", "strut", "suspension", "battery", "coolant",
    "radiator", "thermostat", "transmission", "clutch", "alternator",
    "starter", "belt", "tire", "wheel", "alignment", "wiper", "bulb",
    "headlight", "exhaust", "muffler", "axle", "bearing", "pump", "hose",
    "gasket", "mount", "tune", "fluid", "flush", "injector", "turbo",
    "differential", "driveshaft", "sway", "tie", "control",
}
# Position qualifiers — disambiguate (front vs rear pads) but carry no service
# meaning on their own, so a line matching ONLY a qualifier isn't relevant.
_QUALIFIER_WORDS = {"front", "rear", "left", "right", "upper", "lower",
                    "driver", "passenger", "side", "inner", "outer"}


def _svc_words(text: str) -> set[str]:
    out: set[str] = set()
    for w in re.split(r"\W+", (text or "").lower()):
        if len(w) < 3 or w in _COMPLAINT_STOP:
            continue
        out.add(_SVC_SYNONYMS.get(w, w))
    return out


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def classify_text(text: str) -> Optional[str]:
    """Canonical service-type for a free-text complaint OR a corpus job name.

    Mirrors services.service_skeleton.classify_service but works on raw text
    (the corpus side has no Hermes JobSpec). Used as the PRIMARY matching gate:
    deterministic type equality replaces fuzzy keyword overlap, so an "oil
    change" query can never bind to an "oil leak diagnostics" RO."""
    t = (text or "").lower()
    if "brake" in t or "squeak" in t or "squeal" in t or "grind" in t:
        # Pad/rotor signal — what a "front/rear brake service" actually is.
        has_pad = any(w in t for w in
                      ("pad", "rotor", "disc", "shoe", "caliper"))
        # Brake ELECTRONICS / diagnostics — ABS, booster, control-unit/module
        # coding, wheel-speed sensor faults, warning lights. They share the
        # word "brake" but are NOT a pad/rotor job and must never bind a
        # "front brake service" request to an ABS/booster RO (RO#47076
        # mis-map: a 2017 Audi A4 booster-sensor + ABS-module RO came back as a
        # "front brake" match — Sergio June 13). \babs\b avoids "absorber".
        has_diag = bool(re.search(r"\babs\b", t)) or any(w in t for w in (
            "booster", "module", "control unit", "hydraulic unit",
            "wheel speed", "diagnos", "fault", "warning light", "coding"))
        if has_diag and not has_pad:
            return None
        if "fluid" in t and "brake" in t and not has_pad:
            return "brake_fluid_service"
        side = "rear" if "rear" in t else "front"
        return f"brake_{side}_full"
    # Transmission BEFORE oil: "transmission oil service" / "trans oil pan"
    # must classify as transmission — the oil branch would otherwise grab it
    # on the words "oil service" and an oil-change query would pull
    # transmission work.
    _is_trans = "transmission" in t or re.search(r"\btrans\b|\batf\b", t)
    if _is_trans and ("fluid" in t or "service" in t or "oil" in t
                      or "filter" in t or "gasket" in t or "pan" in t):
        return "transmission_fluid_service"
    if "oil" in t and not _is_trans and (
            "change" in t or "service" in t or "filter" in t
            or "lubricat" in t or re.search(r"\beos\b", t)):
        return "oil_change_standard"
    if "shock" in t or "strut" in t or "suspension" in t:
        side = "rear" if "rear" in t else "front"
        return f"shocks_{side}"
    if "spark" in t or "ignition coil" in t:
        return "spark_plugs"
    if "battery" in t:
        return "battery"
    if "coolant" in t or "radiator" in t or "thermostat" in t or "overheat" in t:
        return "cooling_system"
    if "tire" in t and ("rotat" in t or "balanc" in t or "new" in t):
        return "tires"
    if "cabin" in t and "filter" in t:
        return "cabin_filter"
    if "air filter" in t:
        return "engine_air_filter"
    if "wiper" in t:
        return "wipers"
    if "alternator" in t or "starter" in t:
        return "charging_starting"
    return None


def _type_compatible(lt: Optional[str], q_type: Optional[str]) -> bool:
    """Is a line/job classified as `lt` part of the requested service `q_type`?

    Tighter than a raw family ('brake') match: a brake FLUID flush is its own
    service and must NOT fold into a pad/rotor brake job — the shop does not
    flush brake fluid as part of a front/rear brake service (Sergio June 13:
    'brake fluid is on there but we are not doing a flush'). Without this,
    'fluid' (a supply word, and a brake-family classification) leaks the flush
    line back into every brake estimate."""
    if not lt or not q_type:
        return False
    if lt.split("_")[0] != q_type.split("_")[0]:
        return False
    if q_type in ("brake_front_full", "brake_rear_full") and lt == "brake_fluid_service":
        return False
    return True


def _parse_posted(s: Optional[str]) -> float:
    """'Jun 10, 2026' -> sortable ordinal (0.0 when unparseable). Used to
    prefer the most RECENT matching RO — fresher prices, current SOP."""
    if not s:
        return 0.0
    from datetime import datetime as _dt
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return float(_dt.strptime(s.strip(), fmt).toordinal())
        except ValueError:
            continue
    return 0.0


# ----------------------------------------------------------- recent-price refresh
# A matched RO can be old; even the freshest MATCHING RO may carry part prices
# from a year or two back, and the shop's parts pricing has spiked recently
# (Sergio June 12: "the last 5 years have been the biggest spike in pricing").
# So for each part we expose the MOST RECENT price the shop billed for that SAME
# part anywhere in the corpus — "recheck the fresh price from the old data".
# Identity is (normalized part_number + normalized description): part_number
# ALONE is unsafe because the corpus reuses generic SKUs ("INVENTORY", "5W-40",
# "05CL") across unrelated items at wildly different prices. Cached per db_path,
# built on first use (the corpus only changes on re-ingest, which restarts the
# worker, so a process-lifetime cache can't go stale).

_PRICE_INDEX: dict[str, dict[tuple[str, str], tuple[float, float, str, str]]] = {}

# Generic non-part SKUs — never an identity to refresh on, even with a desc.
_JUNK_PN = {
    "INVENTORY", "SUPPLIES", "SHOPSUPPLIES", "SHOP", "MISC", "NA", "NONE",
    "SUBLET", "FREIGHT", "CORE", "DISPOSAL", "FEE", "HAZMAT", "EPA", "SHOPFEE",
}


def _norm_pn(pn) -> Optional[str]:
    if pn is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", str(pn)).upper()
    return s or None


def _norm_desc_key(desc) -> str:
    return re.sub(r"\s+", " ", (desc or "").strip().lower())[:40]


def _build_price_index(db_path: str) -> dict:
    """Scan the corpus once → {(norm_pn, norm_desc): (date_ordinal, unit, ro, date_str)}
    keeping only the most-recent priced occurrence of each identity."""
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ro_number, date_posted, jobs_json FROM ros").fetchall()
    conn.close()
    idx: dict[tuple[str, str], tuple[float, float, str, str]] = {}
    for r in rows:
        d_str = r["date_posted"]
        d_ord = _parse_posted(d_str)
        if not d_ord:
            continue
        try:
            jobs = json.loads(r["jobs_json"]) if r["jobs_json"] else []
        except Exception:
            continue
        for jb in jobs:
            for p in (jb.get("parts") or []):
                pn = _norm_pn(p.get("part_number"))
                if not pn or pn in _JUNK_PN or len(pn) < 4:
                    continue
                desc = _norm_desc_key(p.get("description"))
                if not desc:
                    continue
                # Index the WHOLESALE cost (the unit the parts matrix marks up),
                # not the billed retail — the refresh updates cost, then re-applies
                # the matrix. Fall back to retail unit only if no cost recorded.
                cost = p.get("cost")
                try:
                    unit = round(float(cost), 2) if cost not in (None, "") else 0.0
                except (TypeError, ValueError):
                    unit = 0.0
                if unit <= 0:
                    try:
                        unit = round(float(p.get("total")) / (int(p.get("qty") or 1) or 1), 2)
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue
                if unit <= 0:
                    continue
                key = (pn, desc)
                prev = idx.get(key)
                if prev is None or d_ord > prev[0]:
                    idx[key] = (d_ord, unit, r["ro_number"], d_str)
    return idx


def latest_corpus_price(part_number, description,
                        *, db_path: str = DB_DEFAULT) -> Optional[dict]:
    """Most-recent WHOLESALE cost the shop paid for this exact (part_number,
    description) across the whole corpus (the unit the parts matrix marks up).
    Returns {unit, date_ordinal, date, ro_number} or None when the part can't be
    confidently identified (junk/short SKU, missing description)."""
    pn = _norm_pn(part_number)
    desc = _norm_desc_key(description)
    if not pn or pn in _JUNK_PN or len(pn) < 4 or not desc:
        return None
    if db_path not in _PRICE_INDEX:
        _PRICE_INDEX[db_path] = _build_price_index(db_path)
    hit = _PRICE_INDEX[db_path].get((pn, desc))
    if not hit:
        return None
    d_ord, unit, ro, d_str = hit
    return {"unit": unit, "date_ordinal": d_ord, "date": d_str, "ro_number": ro}


# --------------------------------------------------------------- flat-fee pricing
# Some standard services are sold at a near-fixed price per vehicle class rather
# than a parts+labor buildup (Sergio June 12: "brake services, it's a flat fee …
# dial in the basic stuff like oil changes into flat fees"). For those, the most
# honest price is the one the shop ACTUALLY charged — the median of past ROs for
# the same service on a comparable vehicle. This replaces a possibly-wrong live
# buildup (the "$494 should be $200–300" case) with the shop's real number.

_FLAT_FEE_MIN_SAMPLES = 4  # below this the median isn't representative


def _money(v) -> float:
    """Coerce a corpus total (str '1,234.50' / '$120' or a number) to float."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def service_flat_fee(service_type: Optional[str], year: Optional[int],
                     make: Optional[str], model: Optional[str] = None,
                     *, db_path: str = DB_DEFAULT) -> Optional[dict]:
    """Shop's typical FLAT price (pre-tax) for a standard service on a comparable
    vehicle, from the corpus. For every same-make RO, classify each job; for jobs
    whose canonical type == service_type, take the job's pre-tax total (labor +
    parts). Prefer samples within the year window; fall back to make-wide if too
    few. Returns {median, low, high, n, basis} or None when too sparse to trust."""
    if not service_type or not make:
        return None
    make_n = _norm(make)
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT year, make, jobs_json FROM ros").fetchall()
    conn.close()

    totals_year: list[float] = []
    totals_make: list[float] = []
    for r in rows:
        if _norm(r["make"]) != make_n and make_n not in _norm(r["make"]):
            continue
        ygap = None
        if year and r["year"]:
            try:
                ygap = abs(int(year) - int(r["year"]))
            except (TypeError, ValueError):
                ygap = None
        try:
            jobs = json.loads(r["jobs_json"]) if r["jobs_json"] else []
        except Exception:
            continue
        for jb in jobs:
            if classify_text(jb.get("name") or "") != service_type:
                continue
            jt = round(sum(_money(l.get("total")) for l in (jb.get("labor") or []))
                       + sum(_money(p.get("total")) for p in (jb.get("parts") or [])), 2)
            if jt <= 0:
                continue
            totals_make.append(jt)
            if ygap is not None and ygap <= _MAX_YEAR_GAP:
                totals_year.append(jt)

    if len(totals_year) >= _FLAT_FEE_MIN_SAMPLES:
        totals, basis = totals_year, f"{_canonical_make(make)} ±{_MAX_YEAR_GAP}yr"
    elif len(totals_make) >= _FLAT_FEE_MIN_SAMPLES:
        totals, basis = totals_make, f"all {_canonical_make(make)}"
    else:
        return None

    q1, _med, q3 = statistics.quantiles(totals, n=4)
    return {
        "service_type": service_type,
        "median": round(statistics.median(totals), 2),
        "low": round(q1, 2),
        "high": round(q3, 2),
        "n": len(totals),
        "basis": basis,
    }


def _model_token_score(q_model_toks: set[str], series_prefix: Optional[str],
                       r_model: str) -> float:
    """Word-boundary model matching. Substring matching was a wrong-map source:
    's60' is a substring of 's600' (different car). Tokens must match whole
    words; the series-prefix fallback handles 'C-Class' ↔ 'C300'."""
    if not q_model_toks:
        return 0.0
    r_words = set(re.split(r"[\s\-/]+", r_model))
    hits = sum(1 for t in q_model_toks if t in r_words)
    score = hits / len(q_model_toks)
    if score == 0 and series_prefix and re.match(rf"^{series_prefix}\d", r_model):
        score = 0.8
    return score


def _extract_relevant_jobs(all_jobs: list[dict], q_type: Optional[str],
                           q_svc: set[str]) -> tuple[list[dict], bool]:
    """Pull only the labor/parts lines relevant to the requested service out of
    an RO's jobs. Returns (kept_jobs, filtered).

    Deterministic-first, mirroring the matcher tiers: when the request has a
    canonical type, every decision is made by classify_text — a line/job is
    kept when IT classifies to the requested type (or is type-neutral inside a
    dedicated job). The old keyword+supply-word line filter let generic words
    ("fluid", "gasket") drag a transmission service into an "oil change" and an
    oil-cooler job into "front brake pads". Supply lines (cleaning kit etc.)
    ride along ONLY inside a job we already kept for the right reason.

    No keep-all fallback: if the RO holds no content for the requested
    service, kept_jobs comes back empty and the CALLER must reject the match
    (next candidate / live pipeline) — never return the wrong service.
    """
    kept: list[dict] = []
    removed = 0

    def _supply_ok(p: dict) -> bool:
        # A supply line (cleaning kit, grease, shim) rides along only if it is
        # type-NEUTRAL or compatible — never an incompatible sibling. 'fluid'
        # is a supply word AND classifies brake fluid to brake_fluid_service,
        # so without this guard a flush line rides back into a pad job through
        # the supply path even after the family filter drops it.
        if not (_svc_words(p.get("description") or "") & _SUPPLY_WORDS):
            return False
        if not q_type:
            return True  # keyword mode: original supply ride-along
        pt = classify_text(p.get("description") or "")
        return pt is None or _type_compatible(pt, q_type)

    for j in all_jobs:
        jn = j.get("name") or ""
        labor = j.get("labor") or []
        parts = j.get("parts") or []
        # Job-level side gate — for a sided service (front/rear brakes or shocks),
        # skip a job whose NAME names the OPPOSITE axle ("Rear Brake Service" for a
        # front request). classify_text() defaults a generic, side-less "Brake
        # Service" to front, which would otherwise make a rear request silently
        # bind a front job (and vice versa). Generic jobs (no side word) still
        # match either side; same-side jobs match.
        if q_type and ("front" in q_type or "rear" in q_type):
            want = "front" if "front" in q_type else "rear"
            other = "rear" if want == "front" else "front"
            jl = jn.lower()
            if re.search(rf"\b{other}\b", jl) and not re.search(rf"\b{want}\b", jl):
                removed += len(labor) + len(parts)
                continue
        if q_type:
            jtype = classify_text(jn)
            if jtype == q_type or _type_compatible(jtype, q_type):
                # Dedicated job — keep type-neutral + compatible lines; drop
                # lines of a DIFFERENT service (bundled battery) or an
                # incompatible sibling (brake-fluid flush in a pad job).
                fl = [l for l in labor
                      if (lt := classify_text(l.get("description") or "")) is None
                      or _type_compatible(lt, q_type)]
                fp = [p for p in parts
                      if (pt := classify_text(p.get("description") or "")) is None
                      or _type_compatible(pt, q_type)]
            else:
                # Mixed/unrelated job — only lines that THEMSELVES classify
                # compatible, plus compatible/neutral supplies if a real line
                # was kept.
                fl = [l for l in labor
                      if _type_compatible(classify_text(l.get("description") or ""), q_type)]
                fp = [p for p in parts
                      if _type_compatible(classify_text(p.get("description") or ""), q_type)]
                if fl or fp:
                    fp += [p for p in parts if p not in fp and _supply_ok(p)]
        else:
            # Keyword path (no canonical type): a line must share a concrete
            # service noun with the complaint; supplies only ride along.
            def _kw_ok(desc: str) -> bool:
                hits = (_svc_words(desc) & q_svc) - _QUALIFIER_WORDS
                return bool(hits & _SERVICE_NOUNS)
            fl = [l for l in labor if _kw_ok(l.get("description") or "")
                  or _kw_ok(jn)]
            fp = [p for p in parts if _kw_ok(p.get("description") or "")]
            if fl or fp:
                fp += [p for p in parts if p not in fp and _supply_ok(p)]
        # Side guard — for a sided service (front/rear brakes or shocks), drop a
        # kept line whose text names the OPPOSITE axle. A "front brake service"
        # must not carry a "Rear Brake Pad Set" that shared the same RO job, and
        # vice versa. Lines naming neither side, or both, ride along.
        want = ("front" if q_type and "front" in q_type
                else "rear" if q_type and "rear" in q_type else None)
        if want:
            other = "rear" if want == "front" else "front"

            def _ok_side(desc: str) -> bool:
                t = (desc or "").lower()
                return not (other in t and want not in t)
            fl = [l for l in fl if _ok_side(l.get("description"))]
            fp = [p for p in fp if _ok_side(p.get("description"))]

        removed += (len(labor) - len(fl)) + (len(parts) - len(fp))
        if fl or fp:
            kept.append({**j, "labor": fl, "parts": fp})
    return kept, (removed > 0 or len(kept) < len(all_jobs))


def match_job(year: Optional[int], make: Optional[str], model: Optional[str],
              complaint: str, *, vin: Optional[str] = None,
              db_path: str = DB_DEFAULT, threshold: float = 0.55) -> Optional[dict]:
    """Find the single best historical RO for a new query, or None.

    TIERED, deterministic-first matching — fuzzy keywords are the LAST resort,
    not the primary gate (fuzzy-first is what produced wrong maps):

      TIER 1 — exact VIN: the same physical car came back (repeat customer).
               Vehicle identity is certain; only the service must line up.
      TIER 2 — canonical service-type: classify_text(complaint) equals the
               classified type of a job on the RO, plus a strict vehicle gate
               (word-boundary model match ≥ 0.7, year gap ≤ 8).
      TIER 3 — keyword fallback, with SEPARATE minimums (vehicle ≥ 0.7 AND
               service ≥ 0.6) — the old product-only threshold let a perfect
               vehicle drag a weak service match over the line.

    Ties prefer the most RECENT RO (fresh prices), then the more focused one.
    Returns the match dict + match_tier/year_gap so the caller can route
    auto vs advisor_review honestly.
    """
    if not make:
        return None
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    make_n = _norm(make)
    rows = conn.execute("SELECT * FROM ros").fetchall()
    conn.close()

    q_model_toks = {t for t in re.split(r"[\s\-/]+", (model or "").lower()) if len(t) >= 2}
    q_svc = _svc_words(complaint)
    q_type = classify_text(complaint)
    # Specificity gate: no canonical type AND no concrete service noun means
    # this is a diagnosis-style request ("making noise") — a historical
    # estimate for some OTHER car's noise is precisely the wrong answer.
    if not q_type and not (q_svc & _SERVICE_NOUNS):
        return None
    vin_n = _norm(vin) if vin else None
    m_series = re.match(r"^([a-z]{1,3})[\s-]*class\b", (model or "").lower())
    series_prefix = m_series.group(1) if m_series else None

    candidates: list[tuple] = []
    for r in rows:
        if _norm(r["make"]) != make_n and make_n not in _norm(r["make"]):
            continue
        year_gap = abs(int(year) - int(r["year"])) if (year and r["year"]) else 99
        vin_hit = bool(vin_n and r["vin"] and _norm(r["vin"]) == vin_n)
        # Hard year-gap cap (cross-generation parts don't transfer). An exact
        # VIN bypasses it — it IS the same car regardless of catalogue age,
        # though recency still decides ties.
        if not vin_hit and year_gap > _MAX_YEAR_GAP:
            continue

        model_score = _model_token_score(q_model_toks, series_prefix,
                                         (r["model"] or "").lower())
        if not q_model_toks:
            model_score = 0.5
        year_score = 1.0 if year_gap == 0 else max(0.4, 1.0 - year_gap * 0.1)
        veh_score = 1.0 if vin_hit else \
            ((0.7 * model_score + 0.3 * year_score) if model_score else 0.0)

        # Service signals: canonical type equality (deterministic) + keywords.
        names_blob = r["service_names"] or ""
        type_hit = bool(q_type) and any(
            classify_text(seg) == q_type for seg in names_blob.split("|"))
        names = _svc_words(names_blob)
        kw_score = (len(q_svc & names) / len(q_svc)) if q_svc else 0.0

        # Tier assignment (lower rank = better).
        if vin_hit and (type_hit or kw_score >= 0.5):
            tier_rank, svc_score = 0, (1.0 if type_hit else kw_score)
            conf = round(min(0.99, 0.9 + 0.09 * svc_score), 3)
        elif type_hit and veh_score >= 0.7:
            tier_rank, svc_score = 1, 1.0
            conf = round(veh_score, 3)
        elif veh_score >= 0.7 and kw_score >= 0.6 and veh_score * kw_score >= threshold:
            tier_rank, svc_score = 2, kw_score
            conf = round(veh_score * kw_score, 3)
        else:
            continue

        n_services = names_blob.count("|")
        sort_key = (-tier_rank, conf, _parse_posted(r["date_posted"]),
                    -n_services)
        candidates.append((sort_key, tier_rank, r, veh_score, svc_score, conf, year_gap))

    if not candidates:
        return None

    # Try candidates best-first; ACCEPT the first whose RO actually contains
    # content for the requested service. A high-scoring RO can still be wrong
    # in the flesh — e.g. its only brake-classified job is a $0 inspection
    # while its real lines are oil-cooler work. Verifying extracted CONTENT
    # (not just the name blob) before accepting is what stops "front brake
    # pads" returning an oil-cooler estimate.
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _sort, tier_rank, r, veh_score, svc_score, best_base, year_gap in candidates[:10]:
        try:
            all_jobs = json.loads(r["jobs_json"]) if r["jobs_json"] else []
        except json.JSONDecodeError:
            continue
        used_jobs, filtered = _extract_relevant_jobs(all_jobs, q_type, q_svc)
        if not any((j.get("labor") or j.get("parts")) for j in used_jobs):
            continue  # no real content for this service — next candidate
        if q_type:
            # At least ONE kept line must ITSELF classify COMPATIBLE with the
            # requested service — a brake-named job whose lines are all
            # vent-hose work (type-neutral) or only a fluid flush (incompatible
            # sibling) is the wrong content, not a pad/rotor brake estimate.
            if not any(_type_compatible(classify_text(ln.get("description") or ""), q_type)
                       for j in used_jobs
                       for ln in (j.get("labor") or []) + (j.get("parts") or [])):
                continue
        # Value floor: an RO whose relevant lines sum to pocket change ($0
        # comp'd lines, courtesy top-offs) is not a usable estimate — a $3.50
        # "oil change" match must fall through to a candidate with real
        # content, or to the live pipeline.
        kept_value = sum(float(ln.get("total") or 0) for j in used_jobs
                         for ln in (j.get("labor") or []) + (j.get("parts") or []))
        if kept_value < 50.0:
            continue
        match_tier = ("exact_vin", "service_type", "keyword")[tier_rank]
        break
    else:
        return None

    if filtered:
        # Recompute from the kept lines; total=None so the payload re-adds tax.
        def _sum(js, kind):
            return round(sum(float(ln.get("total") or 0)
                             for j in js for ln in (j.get(kind) or [])), 2)
        labor_total = _sum(used_jobs, "labor")
        parts_total = _sum(used_jobs, "parts")
        grand_total = None
    else:
        labor_total = r["labor_total"]
        parts_total = r["parts_total"]
        grand_total = r["total"]

    return {
        "ro_number": r["ro_number"],
        "vehicle": f"{r['year']} {r['make_model']}",
        "year": r["year"], "make": r["make"], "model": r["model"],
        "total": grand_total, "labor_total": labor_total,
        "parts_total": parts_total, "labor_rate": r["labor_rate"],
        "date_posted": r["date_posted"], "odometer": r["odometer"],
        "confidence": best_base,
        "vehicle_score": round(veh_score, 3),
        "service_score": round(svc_score, 3),
        "service_names": r["service_names"],
        "jobs": used_jobs,
        "filtered": filtered,
        "jobs_used": len(used_jobs),
        "jobs_in_ro": len(all_jobs),
        # Honest routing signals for the caller: how this match was made and
        # how far apart the vehicles are. "exact_vin" = same physical car.
        "match_tier": match_tier,
        "year_gap": year_gap,
    }


def find_similar(query_vehicle: str, service: str, db_path: str = DB_DEFAULT,
                 limit: int = 5) -> list[dict]:
    """Coarse nearest-neighbour: filter by make/model tokens, score by
    service-name keyword overlap. A real Phase-C scorer would add year
    proximity + complaint embedding; this proves the lookup path."""
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    toks = [w for w in re.split(r"\W+", query_vehicle.lower()) if len(w) > 1]
    svc = [w for w in re.split(r"\W+", service.lower()) if len(w) > 2]
    rows = conn.execute("SELECT * FROM ros").fetchall()
    conn.close()
    scored = []
    for r in rows:
        veh = (r["make_model"] or "").lower()
        vscore = sum(1 for tok in toks if tok in veh or tok == str(r["year"]))
        names = (r["service_names"] or "").lower()
        sscore = sum(1 for w in svc if w in names)
        if vscore == 0:
            continue
        scored.append((vscore * 2 + sscore, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, r in scored[:limit]:
        out.append({"score": score, "ro_number": r["ro_number"],
                    "vehicle": f"{r['year']} {r['make_model']}",
                    "total": r["total"], "services": r["service_names"]})
    return out


def _main() -> None:
    ap = argparse.ArgumentParser(description="Historical RO corpus (Phase B)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_ing = sub.add_parser("ingest"); p_ing.add_argument("json_path"); p_ing.add_argument("--db", default=DB_DEFAULT)
    p_st = sub.add_parser("stats"); p_st.add_argument("--db", default=DB_DEFAULT)
    p_fd = sub.add_parser("find"); p_fd.add_argument("vehicle"); p_fd.add_argument("service"); p_fd.add_argument("--db", default=DB_DEFAULT)
    p_m = sub.add_parser("match")
    p_m.add_argument("year", type=int); p_m.add_argument("make"); p_m.add_argument("model")
    p_m.add_argument("complaint")
    p_m.add_argument("--threshold", type=float, default=0.55)
    p_m.add_argument("--db", default=DB_DEFAULT)
    args = ap.parse_args()

    if args.cmd == "ingest":
        raw = Path(args.json_path).read_text(encoding="utf-8")
        if args.json_path.endswith(".jsonl"):
            recs = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
        else:
            data = json.loads(raw)
            recs = data.get("records", data if isinstance(data, list) else [])
        print(json.dumps(ingest(recs, args.db), indent=2))
    elif args.cmd == "stats":
        print(json.dumps(stats(args.db), indent=2))
    elif args.cmd == "find":
        print(json.dumps(find_similar(args.vehicle, args.service, args.db), indent=2))
    elif args.cmd == "match":
        m = match_job(args.year, args.make, args.model, args.complaint,
                      db_path=args.db, threshold=args.threshold)
        if not m:
            print("NO MATCH (below threshold) — would fall through to live portals")
        else:
            print(f"MATCH RO#{m['ro_number']} | {m['vehicle']} | conf={m['confidence']} "
                  f"(veh={m['vehicle_score']} svc={m['service_score']})")
            print(f"  total=${m['total']} labor=${m['labor_total']} parts=${m['parts_total']}")
            print(f"  services: {(m['service_names'] or '')[:200]}")


if __name__ == "__main__":
    _main()
