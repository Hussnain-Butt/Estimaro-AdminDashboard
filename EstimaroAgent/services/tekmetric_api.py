"""Tekmetric REST API client — direct push path that bypasses the browser.

Background. The browser-based push (portals/tekmetric.py) is gated by
Tekmetric's login form, which now triggers a reCAPTCHA challenge on every
login from automation IPs. The session lasts weeks once seeded manually
through noVNC, but every cookie drop ends in a multi-hour outage until an
operator clears the puzzle. The official Tekmetric REST API bypasses the
browser entirely — auth is a bearer token (TEKMETRIC_API_KEY), no UI, no
captcha, no session expiry.

This module is the foundation. It exposes:

  * ``TekmetricAPIClient`` — bearer-auth httpx client wrapping the v1 API
    base URL with a shop-scoped helper. Retries idempotent reads once on
    5xx; writes never retry (would risk creating duplicate ROs).

  * ``push_estimate_api(estimate)`` — the worker's entry point, mirrors the
    return shape of the browser path so the caller doesn't have to branch.
    Returns ``(ok: bool, result: dict)``. On failure, ``result['error']``
    is a short operator-readable string; never raises.

Opt-in: the worker only routes to this path when ``TEKMETRIC_USE_API`` is
truthy in .env. Default is the browser path, so a production deploy can
flip the flag, validate one job, then leave it on without touching code.

Endpoint coverage. The Tekmetric public API is shop-scoped and the routes
this module touches are:

    GET  /api/v1/shops/{shop_id}                       — smoke test
    GET  /api/v1/shops/{shop_id}/customers?email=...   — customer lookup
    POST /api/v1/shops/{shop_id}/customers             — create customer
    POST /api/v1/shops/{shop_id}/repair-orders         — create RO

The exact request bodies are best-effort based on the API's general
patterns; if a field name differs in your subscription's version, the
client logs the 4xx body and the worker falls back to the browser path
without retrying the same write.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from loguru import logger

from config import settings


_BASE_URL = os.environ.get(
    "TEKMETRIC_API_BASE", "https://shop.tekmetric.com/api/v1"
).rstrip("/")
_API_TIMEOUT = float(os.environ.get("TEKMETRIC_API_TIMEOUT", "20"))


class TekmetricAPIError(Exception):
    """Raised when the API returns a non-2xx that the caller should surface.

    Carries the HTTP status and a short reason so callers can decide
    whether to retry, fall back, or fail loud.
    """

    def __init__(self, status: int, reason: str, body: Optional[str] = None):
        super().__init__(f"{status} :: {reason}")
        self.status = status
        self.reason = reason
        self.body = body


class TekmetricAPIClient:
    def __init__(self, api_key: Optional[str] = None, shop_id: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "TEKMETRIC_API_KEY", "") or ""
        self.shop_id = str(shop_id or getattr(settings, "TEKMETRIC_SHOP_ID", "") or "")
        if not self.api_key or not self.shop_id:
            raise RuntimeError(
                "TEKMETRIC_API_KEY and TEKMETRIC_SHOP_ID must be set in .env "
                "before the API push path can run"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _shop_url(self, suffix: str) -> str:
        s = suffix.lstrip("/")
        return f"{_BASE_URL}/shops/{self.shop_id}/{s}"

    async def _request(self, client: httpx.AsyncClient, method: str,
                       url: str, *, json: Any = None,
                       params: Optional[dict] = None) -> dict:
        try:
            r = await client.request(method, url, headers=self._headers(),
                                     json=json, params=params,
                                     timeout=_API_TIMEOUT)
        except httpx.RequestError as e:
            # Network-level error — let the caller fall back to browser path
            # rather than retrying a write that may have already taken effect.
            raise TekmetricAPIError(
                0, f"transport_error: {type(e).__name__}", str(e)[:200]
            )
        if r.status_code >= 400:
            body = (r.text or "")[:400]
            raise TekmetricAPIError(r.status_code, r.reason_phrase or "http_error", body)
        try:
            return r.json()
        except Exception:
            return {}

    # ---- Endpoints -------------------------------------------------------

    async def ping_shop(self) -> dict:
        """Cheap auth smoke test. Returns the shop record on success.

        Useful for validating credentials at startup or right before a
        push so the worker can fall back to the browser path on bad auth
        without burning an actual RO attempt.
        """
        async with httpx.AsyncClient() as client:
            return await self._request(client, "GET", self._shop_url(""))

    async def find_customer_by_email(self, email: str) -> Optional[dict]:
        if not email:
            return None
        async with httpx.AsyncClient() as client:
            try:
                data = await self._request(
                    client, "GET", self._shop_url("customers"),
                    params={"email": email, "limit": 1},
                )
            except TekmetricAPIError as e:
                if e.status == 404:
                    return None
                raise
        results = data.get("results") or data.get("data") or []
        if isinstance(data, list):
            results = data
        return results[0] if results else None

    async def create_customer(self, customer: dict) -> dict:
        """Body: {firstName, lastName, email, phone}. Returns created record."""
        async with httpx.AsyncClient() as client:
            return await self._request(
                client, "POST", self._shop_url("customers"), json=customer,
            )

    async def create_repair_order(self, ro: dict) -> dict:
        """Body: {customerId, vehicle:{...}, jobs:[{name, laborHours, laborRate, parts:[...]}]}.

        Returns the created RO record (with id + repairOrderNumber).
        """
        async with httpx.AsyncClient() as client:
            return await self._request(
                client, "POST", self._shop_url("repair-orders"), json=ro,
            )


# --------------------------------------------------------------------------- helpers


def _split_customer_name(full: str) -> tuple[str, str]:
    """Tekmetric expects firstName + lastName; FE captures one display name.

    Split on the LAST whitespace so "Maria del Rosario Hernandez" maps to
    firstName="Maria del Rosario", lastName="Hernandez". Falls back to
    treating the whole thing as firstName when there's no whitespace.
    """
    parts = (full or "").strip().split()
    if not parts:
        return "Customer", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def _shape_ro_payload(estimate: dict, customer_id: int | str) -> dict:
    """Map the worker's `estimate` dict to a Tekmetric repair-order POST body."""
    veh = estimate.get("vehicleInfo") or {}
    labor = estimate.get("laborItems") or []
    parts = estimate.get("partsItems") or []
    vin = veh.get("vin") or estimate.get("vin") or ""

    jobs = []
    if labor:
        # Tekmetric models a "job" as a labor row with attached parts. We
        # collapse into one job named after the customer's service request
        # so all parts land in the same line on the RO, mirroring how the
        # browser-driven flow created them.
        job_name = (estimate.get("serviceRequest") or labor[0].get("description") or "Service").strip()
        total_hours = 0.0
        for lr in labor:
            try:
                total_hours += float(lr.get("hours") or 0)
            except (TypeError, ValueError):
                pass
        rate = float(labor[0].get("rate") or 150.0)
        ro_parts = []
        for p in parts:
            try:
                cost = float(p.get("cost") or 0)
            except (TypeError, ValueError):
                cost = 0.0
            ro_parts.append({
                "description": p.get("description") or "Part",
                "partNumber": p.get("partNumber"),
                "vendorSku": p.get("vendorSku"),
                "quantity": int(p.get("quantity") or 1),
                "cost": cost,
                "retail": round(cost * (1 + float(p.get("markup") or 0) / 100.0), 2),
            })
        jobs.append({
            "name": job_name,
            "laborHours": round(total_hours, 2),
            "laborRate": rate,
            "parts": ro_parts,
        })

    return {
        "customerId": customer_id,
        "vehicle": {
            "vin": vin,
            "year": veh.get("year"),
            "make": veh.get("make"),
            "model": veh.get("model"),
            "trim": veh.get("trim"),
            "engine": veh.get("engine"),
        },
        "jobs": jobs,
        "source": "Estimaro",
    }


# --------------------------------------------------------------------------- entry point


async def push_estimate_api(estimate: dict) -> tuple[bool, dict]:
    """Worker-facing entry. Mirrors portals.tekmetric.push_estimate's shape.

    Returns ``(ok, result)`` where on success ``result`` contains
    ``ro_number``, ``ro_url`` and counts; on failure it contains ``error``.
    Never raises — caller can use the same try/except scaffold it had for
    the browser path.
    """
    try:
        client = TekmetricAPIClient()
    except RuntimeError as e:
        return False, {"error": str(e)}

    customer_info = (estimate.get("customer") or estimate.get("customerInfo") or {})
    raw_name = customer_info.get("name") or (
        f"{customer_info.get('firstName', '')} {customer_info.get('lastName', '')}".strip()
    )
    email = customer_info.get("email") or estimate.get("customerEmail")
    phone = customer_info.get("phone") or estimate.get("customerPhone")

    # 1. Resolve customer (find by email if available, else create).
    try:
        existing = await client.find_customer_by_email(email) if email else None
        if existing:
            customer_id = existing.get("id") or existing.get("customerId")
            customer_action = "found_existing"
        else:
            first, last = _split_customer_name(raw_name)
            created = await client.create_customer({
                "firstName": first or "Customer",
                "lastName": last or "",
                "email": email,
                "phone": phone,
            })
            customer_id = created.get("id") or created.get("customerId")
            customer_action = "created"
        if not customer_id:
            return False, {"error": "customer_create_failed :: API returned no id"}
    except TekmetricAPIError as e:
        return False, {"error": f"customer_step :: {e.reason} (status {e.status})"}

    # 2. Create the repair order with the labor + parts payload.
    try:
        ro_payload = _shape_ro_payload(estimate, customer_id)
        ro = await client.create_repair_order(ro_payload)
    except TekmetricAPIError as e:
        return False, {
            "error": f"repair_order_step :: {e.reason} (status {e.status})",
            "_body": (e.body or "")[:200],
        }

    ro_number = ro.get("repairOrderNumber") or ro.get("number") or ro.get("id")
    ro_id = ro.get("id") or ro_number
    ro_url = (
        f"https://shop.tekmetric.com/admin/shop/{client.shop_id}/repair-orders/{ro_id}"
        if ro_id else None
    )

    labor_lines_added = sum(1 for _ in (estimate.get("laborItems") or []))
    parts_lines_added = sum(1 for _ in (estimate.get("partsItems") or []))

    logger.info(
        f"[tekmetric_api] RO {ro_number!s} created via API "
        f"(customer={customer_action}, labor={labor_lines_added}, parts={parts_lines_added})"
    )
    return True, {
        "ro_number": str(ro_number) if ro_number else "",
        "ro_url": ro_url,
        "customer_action": customer_action,
        "vehicle_action": "attached_to_ro",
        "labor_lines_added": labor_lines_added,
        "parts_lines_added": parts_lines_added,
        "note": "Pushed via Tekmetric REST API (TEKMETRIC_USE_API=1)",
    }
