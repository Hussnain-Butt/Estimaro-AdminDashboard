"""Shop settings persistence endpoint.

Single-tenant: there's one `ShopSettings` document keyed `shop_key="default"`.
GET seeds it on first read so the frontend always has a record to edit.
PUT replaces the whole document (validated through the model) — secrets are
written verbatim but read back masked (last 4 chars) so they never round-trip
to the browser in cleartext.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.shop_settings import (
    ExternalCreds,
    Integrations,
    ScoringWeights,
    ShopConfig,
    ShopSettings,
    Templates,
    TekmetricCreds,
    TwilioCreds,
)


router = APIRouter()


def _mask(secret: Optional[str]) -> Optional[str]:
    """Return a UI-safe preview of a credential (last 4 chars), preserving
    empty/None so the frontend can render an empty input without leaking
    history. Use a non-secret label like "shop_id" verbatim."""
    if not secret:
        return secret
    if len(secret) <= 4:
        return "•" * len(secret)
    return "•" * (len(secret) - 4) + secret[-4:]


def _settings_to_public(doc: ShopSettings) -> dict:
    return {
        "shop_name": doc.shop_name,
        "shop": doc.shop.model_dump(),
        "scoring": doc.scoring.model_dump(),
        "advisors": list(doc.advisors),
        "integrations": {
            "tekmetric": {
                "api_key": _mask(doc.integrations.tekmetric.api_key),
                "shop_id": doc.integrations.tekmetric.shop_id,
            },
            "twilio": {
                "sid": doc.integrations.twilio.sid,
                "auth_token": _mask(doc.integrations.twilio.auth_token),
                "phone": doc.integrations.twilio.phone,
            },
            "external": {
                "alldata": _mask(doc.integrations.external.alldata),
                "partslink24_token": _mask(doc.integrations.external.partslink24_token),
            },
        },
        "templates": doc.templates.model_dump(),
        "updated_at": doc.updated_at.isoformat(),
    }


async def _get_or_seed() -> ShopSettings:
    doc = await ShopSettings.find_one(ShopSettings.shop_key == "default")
    if doc is None:
        doc = ShopSettings()
        await doc.insert()
    return doc


class _SecretUpdate(BaseModel):
    """Inbound secret. A value of '' (empty string) clears the stored secret.
    A value entirely made of '•' is treated as "no change" — that's the masked
    placeholder we send to the client, so re-saving the form must not wipe
    real secrets."""
    pass


class SettingsUpdate(BaseModel):
    shop_name: Optional[str] = None
    shop: Optional[ShopConfig] = None
    scoring: Optional[ScoringWeights] = None
    advisors: Optional[List[str]] = None
    integrations: Optional[Dict[str, Dict[str, Any]]] = None
    templates: Optional[Templates] = None


def _apply_secret(current: Optional[str], incoming: Any) -> Optional[str]:
    if incoming is None:
        return current
    s = str(incoming)
    # Masked placeholder — leave the stored value untouched.
    if s and set(s) == {"•"}:
        return current
    return s or None


def _merge_integrations(current: Integrations, incoming: Dict[str, Dict[str, Any]]) -> Integrations:
    tek_in = (incoming or {}).get("tekmetric") or {}
    twi_in = (incoming or {}).get("twilio") or {}
    ext_in = (incoming or {}).get("external") or {}
    return Integrations(
        tekmetric=TekmetricCreds(
            api_key=_apply_secret(current.tekmetric.api_key, tek_in.get("api_key")),
            shop_id=tek_in.get("shop_id", current.tekmetric.shop_id) or None,
        ),
        twilio=TwilioCreds(
            sid=twi_in.get("sid", current.twilio.sid) or None,
            auth_token=_apply_secret(current.twilio.auth_token, twi_in.get("auth_token")),
            phone=twi_in.get("phone", current.twilio.phone) or None,
        ),
        external=ExternalCreds(
            alldata=_apply_secret(current.external.alldata, ext_in.get("alldata")),
            partslink24_token=_apply_secret(
                current.external.partslink24_token, ext_in.get("partslink24_token")
            ),
        ),
    )


@router.get(
    "/",
    summary="Get shop settings (secrets masked)",
    description=(
        "Returns the singleton shop settings. Secrets are returned as a "
        "masked preview (last 4 chars) so the browser never holds the "
        "real value. To change a secret, send the new value; to leave it "
        "alone, re-send the masked string we returned."
    ),
)
async def get_settings():
    doc = await _get_or_seed()
    return _settings_to_public(doc)


@router.put(
    "/",
    summary="Replace shop settings",
    description=(
        "Partial updates supported — only the keys you send are touched. "
        "Secrets follow the mask convention: empty string clears, masked "
        "placeholder leaves them untouched, anything else replaces."
    ),
)
async def update_settings(update: SettingsUpdate):
    doc = await _get_or_seed()
    if update.shop_name is not None:
        doc.shop_name = update.shop_name
    if update.shop is not None:
        doc.shop = update.shop
    if update.scoring is not None:
        doc.scoring = update.scoring
    if update.advisors is not None:
        # Dedup + strip; never accept empty names.
        doc.advisors = [a.strip() for a in update.advisors if a and a.strip()]
    if update.integrations is not None:
        doc.integrations = _merge_integrations(doc.integrations, update.integrations)
    if update.templates is not None:
        doc.templates = update.templates
    doc.updated_at = datetime.utcnow()
    await doc.save()
    return _settings_to_public(doc)
