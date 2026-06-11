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
    parts = make_model.split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else None)


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
                         complaint: str, result: dict,
                         db_path: str = DB_DEFAULT) -> Optional[str]:
    """Phase E — add a freshly worker-built estimate to the corpus so a repeat
    (vehicle, service) query matches it INSTANTLY next time (continuous
    learning). Stored under a synthetic 'EST-' key so it's distinguishable from
    a real paid Tekmetric RO. No-op for empty / $0 estimates."""
    labor_items = result.get("laborItems") or []
    parts_items = result.get("partsItems") or []
    bd = result.get("breakdown") or {}
    total = bd.get("total")
    if not labor_items or not (total and float(total) > 0):
        return None

    vin8 = re.sub(r"[^A-Za-z0-9]", "", (vin or "anon"))[-8:].upper() or "ANON"
    svc_key = _norm(complaint)[:10] or "svc"
    ro_number = f"EST-{vin8}-{svc_key}"
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
        (ro_number, None, year, make, model, make_model, vin, None, None, None,
         float(total), bd.get("laborTotal"), bd.get("partsTotal"),
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


def match_job(year: Optional[int], make: Optional[str], model: Optional[str],
              complaint: str, *, db_path: str = DB_DEFAULT,
              threshold: float = 0.55) -> Optional[dict]:
    """Find the single best historical RO for a new (year, make, model,
    complaint) query, or None if nothing clears `threshold`.

    Conservative by design: showing the WRONG past estimate erodes trust far
    more than missing a match (we just fall through to the live portals). So
    the make must match, and the score multiplies a vehicle component by a
    service/complaint component — a strong vehicle alone never qualifies.

    Returns a dict: {ro_number, vehicle, total, labor_total, parts_total,
    date_posted, confidence, vehicle_score, service_score, jobs, raw}.
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
    # Mercedes/BMW class naming: NHTSA decodes "C-Class" / "E-Class" / "GLC-Class"
    # but Tekmetric stores the trim ("C300", "E350", "GLC300"). The class token
    # ("class") never appears in the trim, so token overlap misses a car Sergio
    # has clearly serviced. Extract the series prefix (C / E / GLC) and also
    # accept a corpus model that starts with it followed by a digit.
    m_series = re.match(r"^([a-z]{1,3})[\s-]*class\b", (model or "").lower())
    series_prefix = m_series.group(1) if m_series else None

    best = None
    best_base = 0.0
    best_sort = -1.0
    for r in rows:
        if _norm(r["make"]) != make_n and make_n not in _norm(r["make"]):
            continue
        # Hard year-gap cap: a 2023 car must NOT match a 1999 one of the same
        # nameplate — different generation, different part numbers entirely.
        # 8 years keeps same/adjacent generations (where parts still apply) and
        # rejects cross-generation matches outright.
        if year and r["year"] and abs(int(year) - int(r["year"])) > _MAX_YEAR_GAP:
            continue
        # Vehicle score: model-family overlap + year proximity.
        r_model = (r["model"] or "").lower()
        if q_model_toks:
            hits = sum(1 for t in q_model_toks if t in r_model)
            model_score = hits / len(q_model_toks)
            # Series-prefix fallback for "<letter>-Class" ↔ trim ("C-Class"↔"C300").
            if model_score == 0 and series_prefix and \
                    re.match(rf"^{series_prefix}\d", r_model):
                model_score = 0.8
        else:
            model_score = 0.5
        if year and r["year"]:
            dy = abs(int(year) - int(r["year"]))
            year_score = 1.0 if dy == 0 else max(0.4, 1.0 - dy * 0.1)
        else:
            year_score = 0.6
        veh_score = (0.7 * model_score + 0.3 * year_score) if model_score else 0.0

        # Service score: complaint words found among the RO's job names.
        names = _svc_words(r["service_names"] or "")
        svc_score = (len(q_svc & names) / len(q_svc)) if q_svc else 0.0

        base = round(veh_score * svc_score, 4)
        if base < threshold:
            continue
        # Tiebreaker: when scores tie, prefer the MORE FOCUSED RO (fewer jobs) —
        # a 23-job Sprinter visit that happens to include brakes is a worse
        # source for a "front brake pads" query than a dedicated brake RO. Cheap
        # (no job-JSON parse): count the pipe-separated service names.
        n_services = (r["service_names"] or "").count("|")
        sort_score = base - 0.0005 * n_services
        if sort_score > best_sort:
            best_sort, best_base, best = sort_score, base, (r, veh_score, svc_score)

    if not best:
        return None
    r, veh_score, svc_score = best
    try:
        all_jobs = json.loads(r["jobs_json"]) if r["jobs_json"] else []
    except json.JSONDecodeError:
        all_jobs = []

    # LINE-ITEM FILTER — keep only the labor/part LINES relevant to the request.
    # A single Tekmetric RO/job often bundles unrelated work from one visit
    # (e.g. "front brakes" plus a battery + a bulb on the same ticket). Job- or
    # RO-level filtering can't separate those, so we filter individual lines: a
    # line is relevant if its OWN description shares a service word with the
    # complaint, or names a generic service supply (cleaner/kit/fluid/…).
    def _line_relevant(desc: str, fallback: str = "") -> bool:
        words = _svc_words(desc) or _svc_words(fallback)
        # A match on a QUALIFIER alone (front/rear/left/…) doesn't count — it
        # would wrongly keep "tire pressure FRONT 47" for a "front brake" query.
        # Require a real service noun (brake/pad/rotor/…) or a supply word.
        svc_hits = (words & q_svc) - _QUALIFIER_WORDS
        return bool(svc_hits) or bool(words & _SUPPLY_WORDS)

    used_jobs = all_jobs
    filtered = False
    if q_svc:
        kept_jobs: list[dict] = []
        removed = 0
        for j in all_jobs:
            jn = j.get("name") or ""
            fl = [l for l in (j.get("labor") or [])
                  if _line_relevant(l.get("description") or "", jn)]
            fp = [p for p in (j.get("parts") or [])
                  if _line_relevant(p.get("description") or "")]
            removed += (len(j.get("labor") or []) - len(fl)) + \
                       (len(j.get("parts") or []) - len(fp))
            if fl or fp:
                kept_jobs.append({**j, "labor": fl, "parts": fp})
        if kept_jobs and removed > 0:
            used_jobs, filtered = kept_jobs, True

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
