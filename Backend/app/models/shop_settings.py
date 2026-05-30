"""Shop-wide configuration persisted as a single document.

We keep one document per shop (currently single-tenant: shop_key = "default")
so the frontend Settings page can save labour rate, parts markup, tax rate,
scoring weights, advisors, notification templates and integration handles in
one round-trip. Secret API keys are stored encrypted-at-rest by MongoDB; we
return masked previews to the client (last 4 chars only) so the page never
leaks credentials back to the browser after a save.
"""
from beanie import Document, Indexed
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional


class ShopConfig(BaseModel):
    labor_rate: float = 150.0
    parts_markup: float = 30.0
    tax_rate: float = 9.25


class ScoringWeights(BaseModel):
    brand: int = 40
    price: int = 35
    distance: int = 25


class TekmetricCreds(BaseModel):
    api_key: Optional[str] = None
    shop_id: Optional[str] = None


class TwilioCreds(BaseModel):
    sid: Optional[str] = None
    auth_token: Optional[str] = None
    phone: Optional[str] = None


class ExternalCreds(BaseModel):
    alldata: Optional[str] = None
    partslink24_token: Optional[str] = None


class Integrations(BaseModel):
    tekmetric: TekmetricCreds = Field(default_factory=TekmetricCreds)
    twilio: TwilioCreds = Field(default_factory=TwilioCreds)
    external: ExternalCreds = Field(default_factory=ExternalCreds)


class Templates(BaseModel):
    email: str = "Dear {{customer}}, your estimate is ready: {{link}}"
    sms: str = "Hi {{customer}}, view your estimate: {{link}}"


class ShopSettings(Document):
    """Singleton-style shop settings document.

    Looked up via `ShopSettings.find_one(ShopSettings.shop_key == "default")`.
    If absent, the Settings GET endpoint seeds it with sensible defaults so
    the frontend always has a record to PATCH.
    """
    shop_key: Indexed(str, unique=True) = "default"
    shop_name: str = "German Sport"
    shop: ShopConfig = Field(default_factory=ShopConfig)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)
    advisors: List[str] = Field(default_factory=lambda: ["Sergio", "Alex", "Jordan"])
    integrations: Integrations = Field(default_factory=Integrations)
    templates: Templates = Field(default_factory=Templates)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "shop_settings"
