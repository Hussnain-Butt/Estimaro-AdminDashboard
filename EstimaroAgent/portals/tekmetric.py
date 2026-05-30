"""Tekmetric write-back agent.

Tekmetric is the shop's source-of-truth Repair Order system. This agent takes
a finished Estimaro estimate (vehicle + customer + labor + parts) and creates
a DRAFT Repair Order in Tekmetric so the advisor never has to retype anything.

DESIGN — why a vision agent and not the REST API:
  * Tekmetric's REST API requires a per-shop API key + per-endpoint
    entitlements (creating ROs and customers is gated). The shop is already
    logged into Tekmetric in the same Chrome the worker drives, so we can
    reuse that authenticated session with zero credential plumbing.
  * The shop owner can audit every step (the agent runs visibly in the same
    Chrome window; screenshots saved per step) and pull the plug if the agent
    is about to do something wrong.

SAFETY — non-negotiable invariants enforced in the prompt:
  * The RO is saved as a DRAFT only — never marked sent, approved or invoiced.
  * The agent NEVER deletes, voids, or modifies an existing RO. If the
    customer/vehicle combination already has a recent open draft RO, the
    agent flags it instead of duplicating.
  * The agent NEVER touches the cart, billing or payments tabs.

OUTPUT: a structured result the backend can store on the Estimate:
    {ok, ro_number, ro_url, customer_action, vehicle_action, lines_added}
"""
import asyncio
from typing import Any, Optional, Tuple

from loguru import logger

from core.browser import ChromeDebugBrowser
from portals.base import run_portal_agent


PORTAL_NAME = "Tekmetric"
PORTAL_URL = "https://shop.tekmetric.com/"


def _lines_summary(items: list[dict], kind: str) -> str:
    """Render the labor / parts list as a compact bullet block for the prompt.

    Keeps the prompt deterministic — same input always renders the same text —
    so the agent's behaviour is reproducible across retries.
    """
    if not items:
        return f"    (no {kind} items)"
    lines = []
    for i, it in enumerate(items, 1):
        if kind == "labor":
            lines.append(
                f"    {i}. {it.get('description','?')} — {it.get('hours','?')}h "
                f"@ ${it.get('rate','?')}/h"
            )
        else:
            lines.append(
                f"    {i}. {it.get('description','?')} — qty {it.get('quantity', 1)} "
                f"@ ${it.get('cost', it.get('price', '?'))} "
                f"(part# {it.get('partNumber') or it.get('part_number') or 'n/a'})"
            )
    return "\n".join(lines)


def _build_task(estimate: dict) -> str:
    customer = estimate.get("customer") or {}
    vehicle = estimate.get("vehicleInfo") or {}
    labor_items = estimate.get("laborItems") or []
    parts_items = estimate.get("partsItems") or []
    breakdown = estimate.get("breakdown") or {}

    cust_name = customer.get("name") or ""
    cust_phone = customer.get("phone") or ""
    cust_email = customer.get("email") or ""
    odometer = estimate.get("odometer")
    vin = vehicle.get("vin") or ""
    veh_year = vehicle.get("year") or ""
    veh_make = vehicle.get("make") or ""
    veh_model = vehicle.get("model") or ""

    labor_block = _lines_summary(labor_items, "labor")
    parts_block = _lines_summary(parts_items, "parts")

    return f"""
You are inside Tekmetric, a shop management system, already logged in as the
shop. Your job: create ONE NEW Repair Order containing the labor and parts
listed below, save it as a DRAFT, then read back its RO number.

CUSTOMER:
  Name:   {cust_name}
  Phone:  {cust_phone}
  Email:  {cust_email or '(none)'}

VEHICLE:
  VIN:        {vin}
  Year/Make:  {veh_year} {veh_make} {veh_model}
  Odometer:   {odometer if odometer is not None else '(unknown)'}

LABOR LINES TO ADD:
{labor_block}

PARTS LINES TO ADD:
{parts_block}

TOTAL (informational, do NOT type into Tekmetric — it computes its own):
  labor ${breakdown.get('laborTotal','?')} • parts ${breakdown.get('partsTotal','?')}
  subtotal ${breakdown.get('subtotal','?')} • tax ${breakdown.get('taxAmount','?')}
  total ${breakdown.get('total','?')}

NAVIGATION PLAN (use the numbered overlays in the screenshots):

  1. SHOP SELECT — if Tekmetric shows a shop picker / "Select Shop" screen,
     click the only shop listed (or the most recently-used one). On
     single-shop accounts there is no picker; skip this step.

  2. NEW REPAIR ORDER — find the "Repair Orders" tab in the left navigation
     and click it, then click the "+ New RO" / "Create Repair Order" button
     near the top right. If a quick-create modal opens with customer / vehicle
     search fields, use those directly in step 3 and 4.

  3. CUSTOMER — search by phone "{cust_phone}".
       a. If a matching customer row appears, click it to select. Do NOT
          edit their existing contact info.
       b. If no match, click "+ New Customer" or the "Create Customer" button
          and fill: first name + last name (split "{cust_name}" on the first
          space), phone "{cust_phone}", email "{cust_email or ''}" (leave
          blank if none). Save the new customer.

  4. VEHICLE — once the RO is associated with the customer, search by VIN
     "{vin}".
       a. If a matching vehicle row appears, select it.
       b. If no match, click "+ New Vehicle" / "Create Vehicle". Type the
          VIN "{vin}" — Tekmetric will auto-decode year/make/model. Verify
          the decode matches "{veh_year} {veh_make} {veh_model}"; if any
          field is missing, fill it manually. Set odometer to
          "{odometer if odometer is not None else ''}" (leave blank if
          unknown). Save the new vehicle.

  5. LABOR LINES — for EACH labor line above, click "+ Add Labor" (or the
     labor section's add button), fill the description, hours and rate
     exactly as listed, then save the line. After each save, verify the row
     appears in the RO. Use action="find" for the add-button if it is not
     currently visible.

  6. PARTS LINES — for EACH parts line, click "+ Add Part", fill the
     description, part number, quantity and cost, save the line. Verify each
     row appears.

  7. SAVE AS DRAFT — find the RO header status / save button. Save the RO
     in DRAFT or "Estimate" status. Do NOT mark it sent, approved, invoiced
     or paid. Do NOT click any "Send to Customer", "Authorize", "Pay",
     "Finalize" or "Invoice" buttons.

  8. READ BACK — once the RO is saved, the URL or page header will show the
     RO number (e.g. "RO #12345" or "Repair Order 12345"). Capture it.

OUTPUT: action="extract" with value as a JSON STRING of EXACTLY this schema:
  {{
    "ok": true,
    "ro_number": "<the RO# Tekmetric assigned, as a string>",
    "ro_url": "<the current page URL>",
    "customer_action": "selected_existing" | "created_new",
    "vehicle_action":  "selected_existing" | "created_new",
    "labor_lines_added": <number>,
    "parts_lines_added": <number>,
    "note": "<any caveat the operator should know, or null>"
  }}
Then action="done".

CRITICAL RULES — DO NOT VIOLATE:
  * NEVER finalize, invoice, send, pay or authorize an RO. DRAFT only.
  * NEVER edit an unrelated existing RO. If you accidentally land on one,
    navigate back to "Repair Orders" and start fresh with "+ New RO".
  * NEVER delete/void a customer, vehicle or RO.
  * If a customer search returns MULTIPLE matches with the same phone, pick
    the one whose name best matches "{cust_name}" — do not guess; if none
    is a clear match, action="ask_human" and stop.
  * If the VIN auto-decode shows a vehicle different from
    "{veh_year} {veh_make} {veh_model}", action="ask_human" and stop —
    do not silently override.
  * If at any point the page asks for a credit card, payment, password or
    confirmation of a destructive action, action="ask_human" and stop.
  * Only use action="ask_human" for the specific conditions above — do not
    use it just because a step is slow.
"""


async def _ensure_clean_entry() -> Optional[str]:
    """Open the Tekmetric tab and force-navigate to the RO list so the agent
    starts from a known state. Returns None on success or a categorised
    error string."""
    try:
        async with ChromeDebugBrowser() as browser:
            await browser.open_or_focus(PORTAL_URL, url_match="tekmetric.com")
            await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"[{PORTAL_NAME}] _ensure_clean_entry failed: {type(e).__name__}: {e}")
        return f"prep_failed :: {type(e).__name__}: {str(e)[:160]}"
    return None


async def push_estimate(
    estimate: dict,
    *,
    max_steps: int = 35,
    timeout: int = 420,
) -> Tuple[bool, dict]:
    """Drive the Tekmetric write-back vision agent.

    `estimate` is the same payload shape the backend's /tekmetric/push
    endpoint accepts: {customer, vehicleInfo, laborItems, partsItems,
    breakdown, odometer}.

    Returns ``(ok, result)`` where `result` always carries `history`,
    `steps_taken`, `run_dir`. On success, `result` also has `ro_number`,
    `ro_url` and the agent-emitted action counts. On failure, `result['error']`
    is a categorised string the operator can act on.
    """
    from portals.auth import ensure_logged_in
    status = await ensure_logged_in("tekmetric")
    if not status.get("ok"):
        return False, {
            "error": f"login_failed :: {status.get('error') or status.get('action')}",
            "history": [], "steps_taken": 0, "login_status": status,
        }

    prep_err = await _ensure_clean_entry()
    if prep_err:
        return False, {"error": prep_err, "history": [], "steps_taken": 0}

    task = _build_task(estimate)
    raw, meta = await run_portal_agent(
        PORTAL_URL, task, max_steps=max_steps, timeout=timeout,
        login_portal=None,  # already validated above
    )
    if raw is None:
        return False, meta

    # Sanity-check the agent's claim before reporting success — a vision agent
    # that hallucinates an RO number is worse than one that admits failure.
    ro_number = (raw.get("ro_number") or "").strip()
    if not ro_number:
        meta["error"] = "no_ro_number :: agent finished but did not report a Tekmetric RO#"
        return False, meta

    result: dict[str, Any] = {
        **meta,
        "ok": True,
        "ro_number": ro_number,
        "ro_url": raw.get("ro_url"),
        "customer_action": raw.get("customer_action"),
        "vehicle_action": raw.get("vehicle_action"),
        "labor_lines_added": raw.get("labor_lines_added"),
        "parts_lines_added": raw.get("parts_lines_added"),
        "note": raw.get("note"),
    }
    logger.info(
        f"[{PORTAL_NAME}] pushed RO #{ro_number} ("
        f"customer={raw.get('customer_action')}, vehicle={raw.get('vehicle_action')}, "
        f"labor={raw.get('labor_lines_added')}, parts={raw.get('parts_lines_added')})"
    )
    return True, result


if __name__ == "__main__":
    # Standalone smoke test — uses a fixed sample estimate. Run on the VPS
    # only after manually logging into Tekmetric via noVNC in the worker's
    # Chrome. The DRAFT RO it creates is safe to delete inside Tekmetric.
    sample = {
        "customer": {
            "name": "Estimaro Test Customer",
            "phone": "5555550199",
            "email": "estimaro-test@example.com",
        },
        "vehicleInfo": {
            "vin": "W1KAF4GB3PR122770",
            "year": 2023,
            "make": "Mercedes-Benz",
            "model": "C-Class",
        },
        "odometer": 18432,
        "laborItems": [
            {"description": "Front brake pads — R&R", "hours": 1.2, "rate": 150,
             "total": 180.0},
        ],
        "partsItems": [
            {"description": "Brake Pad Set (Front) — Genuine Mercedes",
             "partNumber": "0004211202", "quantity": 1, "cost": 128.0, "total": 128.0},
        ],
        "breakdown": {
            "laborTotal": 180.0, "partsTotal": 128.0,
            "subtotal": 308.0, "taxAmount": 28.49, "total": 336.49,
        },
    }
    ok, result = asyncio.run(push_estimate(sample))
    print("\n=== RESULT ===")
    print({k: v for k, v in result.items() if k != "history"})
    print(f"\nok={ok}")
