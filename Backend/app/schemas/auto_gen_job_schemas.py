"""API request/response schemas for auto-generate jobs (separate from Document)."""
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from typing import Optional, List, Any, Dict


class LaborLine(BaseModel):
    description: str
    hours: float
    rate: float
    total: float
    source: str = "ALLDATA"
    skill: Optional[str] = None
    # Base64-encoded data URL of the ALLDATA Parts-and-Labor page the agent
    # extracted this row from. Optional because: (a) older workers don't emit
    # it, (b) loader returns None when the file is missing / too large, and
    # (c) we never want this field's absence to gate the estimate.
    extractionScreenshot: Optional[str] = None
    # Task #15 — determinism signal. status ∈ {matched_preferred,
    # matched_fallback, off_script, no_skeleton}. FE renders a small
    # badge on the labor row so the advisor sees whether the picked
    # row is the canonical one for this service type.
    determinism_status: Optional[str] = None
    determinism_rank: Optional[int] = None
    determinism_preferred: Optional[str] = None
    # Task #14 auto-add flags (applies to labor addons too — Wheel Alignment
    # added for suspension jobs).
    auto_added: bool = False
    auto_added_reason: Optional[str] = None
    # Pricing matrix — the shop's Tekmetric Labor Matrix marks labor up by an
    # hours-tiered multiplier (3% under 1h, ramping to a 19% plateau, easing to
    # 15% on long jobs). `baseAmount` is hours×rate before markup; `total`
    # already includes it. Optional so the historical / flat-pricing paths
    # (which carry no labor markup) don't break.
    baseAmount: Optional[float] = None
    laborMultiplier: Optional[float] = None
    laborMarkupPct: Optional[float] = None


class PartLine(BaseModel):
    description: str
    partNumber: Optional[str] = None
    # Vendor's own SKU for the part — often DIFFERENT from the OEM number
    # (ALLDATA: 8634921 vs SSF: 573003J for the same physical pad). Worker
    # only sets this when the two numbers actually differ, so the UI can
    # show both side-by-side without echoing the same value twice.
    vendorSku: Optional[str] = None
    # Wheel-size / option labels ALLDATA listed under the same OEM that the
    # worker collapsed into this single line (e.g. ["Front Pads (15\" Wheels)",
    # "Front Pads (16\" Wheels)"]). UI renders as "Same SKU fits: ..." so the
    # dedup is disclosed instead of silently swallowing the duplicate row.
    appliesToVariants: Optional[List[str]] = None
    quantity: int = 1
    cost: float = 0.0
    markup: float = 0.0
    total: float = 0.0
    vendor: str = "ALLDATA"
    # When the worker substituted a cheaper vendor quote for ALLDATA's MSRP,
    # the original list price + savings amount come along for the UI to show
    # "Saved $X vs MSRP" beside the line. Both fields are optional — omitted
    # when no substitution happened.
    list_price: Optional[float] = None
    savings_vs_list: Optional[float] = None
    # Recent-price refresh (historical path) — when the matched RO's billed
    # price was older than the shop's most recent corpus price for the same
    # part, the line is repriced to the fresher value. originalCost/Total carry
    # the matched RO's price so the UI can show "$X (old) → $Y (priceDate)".
    priceRefreshed: bool = False
    originalCost: Optional[float] = None
    originalTotal: Optional[float] = None
    priceDate: Optional[str] = None
    priceSourceRO: Optional[str] = None
    # Task #14 — skeleton-driven auto-add (cleaning kit, multi-point
    # inspection). Set to True when the worker injected the line from
    # the service skeleton's addons rather than extracting it from
    # ALLDATA. FE shows an "Auto-added per service type" badge.
    auto_added: bool = False
    auto_added_kind: Optional[str] = None      # "supply" | "inspection"
    auto_added_reason: Optional[str] = None
    # Phase C — set to "Historical RO #<n>" when the line came from a matched
    # past estimate rather than a live ALLDATA/vendor lookup.
    source: Optional[str] = None


class VehicleInfo(BaseModel):
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None


class Breakdown(BaseModel):
    laborTotal: float = 0.0
    partsTotal: float = 0.0
    subtotal: float = 0.0
    taxAmount: float = 0.0
    total: float = 0.0


class ConfidenceBreakdown(BaseModel):
    extraction: float = 0.0
    verification: float = 0.0
    sourcing: float = 0.0
    sourcing_note: Optional[str] = None


class ConfidenceSummary(BaseModel):
    """Aggregate confidence + tier routing for the proposal's Layer 6 gate.

    `tier` ∈ {"auto", "advisor_review", "manual_review"} drives the FE badge
    colour and the policy decision on whether to push to Tekmetric without
    advisor approval. Backend doesn't enforce the tier (Tekmetric push is a
    user click), it just transports the worker's verdict.
    """
    score: float = 0.0
    tier: str = "manual_review"
    breakdown: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    # Optional pre-formatted badge label, e.g. "Historical Match · RO #49442 · 88%".
    label: Optional[str] = None


class JobResult(BaseModel):
    vehicleInfo: VehicleInfo = Field(default_factory=VehicleInfo)
    # Phase C — historical RO mining. When the worker answered this job from
    # Sergio's own past paid estimate (instead of the live ALLDATA + vendor
    # pipeline), `source` is "historical" and `historicalMatch` carries the
    # matched RO number, confidence and matched-vehicle so the FE shows a
    # "Built from your RO #X" banner. Both None on the normal live path.
    source: Optional[str] = None
    historicalMatch: Optional[Dict[str, Any]] = None
    # ALLDATA's banner often shows a more specific sub-model than NHTSA
    # decoded (NHTSA: "VOLVO V70"; ALLDATA: "Volvo XC70 L5-2.4L Turbo"). Same
    # chassis, different label. Surfaced so the UI can show both and the
    # advisor confirms the labor row came from the right catalogue entry.
    alldataMatchedVehicle: Optional[str] = None
    laborItems: List[LaborLine] = Field(default_factory=list)
    partsItems: List[PartLine] = Field(default_factory=list)
    breakdown: Breakdown = Field(default_factory=Breakdown)
    section_path: Optional[str] = None
    extraction_confidence: float = 0.0
    verification_match: bool = False
    verification_confidence: float = 0.0
    verification_reason: Optional[str] = None
    agent_steps: int = 0
    elapsed_sec: float = 0.0
    # Vendor pricing (Worldpac/SSF) for the OEM parts, + best-pick comparison
    vendorQuotes: List[Dict[str, Any]] = Field(default_factory=list)
    vendorComparison: Dict[str, Any] = Field(default_factory=dict)
    # Layer 5: per-part-group consensus across the vendors. Keyed by the
    # requested-part name (mirrors vendorComparison's keys); each value is a
    # dict with median/min/max/outliers/oem_agreement — see worker
    # _compute_consensus for the exact shape. Dict[str,Any] so adding a new
    # field there doesn't require a schema migration.
    consensus: Dict[str, Any] = Field(default_factory=dict)
    # Layer 6: overall confidence + tier. Worker decides; FE renders.
    confidence: Optional[ConfidenceSummary] = None
    # NHTSA recalls active for the decoded vehicle. Empty when none / API
    # unavailable — FE hides the banner. Shape is loose Dict so adding new
    # NHTSA fields doesn't require a schema migration.
    recalls: List[Dict[str, Any]] = Field(default_factory=list)
    # Job-classifier recommended add-ons (pad clips, oil filter, ...).
    # Each entry has {name, kind, reason, hours?, cost?} — FE renders as a
    # read-only panel; advisor adds to estimate manually.
    suggestedAddOns: List[Dict[str, Any]] = Field(default_factory=list)
    # Task #12 — service-type skeleton + coverage report. None when no
    # skeleton matched (uncommon service type or vague complaint); FE
    # hides the panel in that case. When present, includes a
    # `coverage_pct` over always-required components — the headline
    # number for advisor sanity-checking.
    serviceSkeleton: Optional[Dict[str, Any]] = None
    # Flat-fee services (oil change, brakes, plugs, trans fluid) — the shop's
    # median past charge for this service+vehicle, which becomes the headline
    # price instead of the parts+labor buildup. None on variable-priced jobs and
    # on historical matches (those already carry the real billed price). Loose
    # dict: {applied, subtotal, taxAmount, total, low, high, n, basis,
    # computedSubtotal, computedTotal}.
    flatFee: Optional[Dict[str, Any]] = None
    # Task #13 — Repair-Procedure (R-cell) scan output. `items` is a
    # list of {action, component_key, component_phrase, quantity,
    # occurrences, contexts}. `scan_status` reports why a scan didn't
    # produce items (URL not transformable, page text too short, etc.).
    # Always present so the FE can display either the items or the
    # diagnostic, never silently empty.
    repairProcedure: Optional[Dict[str, Any]] = None
    # On-demand vendor price refresh — {refreshed, checked, vendor} summary so
    # the FE can toast "Refreshed N of M part prices from vendors".
    priceRefreshSummary: Optional[Dict[str, Any]] = None


class RefreshPartInput(BaseModel):
    """One estimate line the advisor wants repriced from current vendor stock."""
    description: str = ""
    partNumber: Optional[str] = None
    quantity: int = 1
    cost: Optional[float] = None   # current unit cost — kept when no vendor match


class PriceRefreshRequest(BaseModel):
    """Advisor-triggered: reprice an existing estimate's parts against current
    Worldpac/SSF stock. Carries the VIN (re-decoded worker-side for the vendor
    vehicle context) + the parts to reprice. No ALLDATA run."""
    vin: str = Field(..., min_length=11, max_length=17)
    serviceRequest: str = ""
    parts: List[RefreshPartInput] = Field(default_factory=list)
    laborRate: Optional[float] = 150.0
    taxRate: Optional[float] = 0.0925


class JobSubmitRequest(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17)
    serviceRequest: str = Field(..., min_length=1)
    customerName: str = Field(..., min_length=1)
    customerEmail: Optional[EmailStr] = None
    customerPhone: str = Field(..., min_length=10)
    odometer: Optional[int] = Field(None, ge=0)
    laborRate: Optional[float] = 150.0
    partsMarkup: Optional[float] = 30.0
    taxRate: Optional[float] = 0.0925


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkerClaimResponse(BaseModel):
    """Returned to the worker when it claims a job — includes the input
    fields (vin, serviceRequest, rates...) the worker needs to process it."""
    job_id: str
    status: str
    progress: str
    progress_pct: int
    created_at: datetime
    started_at: Optional[datetime] = None
    # Job inputs the worker pipeline requires
    vin: str
    serviceRequest: str
    customerName: str
    customerEmail: Optional[str] = None
    customerPhone: str
    odometer: Optional[int] = None
    laborRate: float = 150.0
    partsMarkup: float = 30.0
    taxRate: float = 0.0925
    # Job mode — "estimate" (full build) or "price_refresh" (vendor reprice of
    # refresh_payload's parts only). The worker dispatches on this.
    mode: str = "estimate"
    refresh_payload: Dict[str, Any] = Field(default_factory=dict)


class WorkerProgressUpdate(BaseModel):
    progress: str
    progress_pct: int = 0


class WorkerResultPayload(BaseModel):
    result: JobResult


class WorkerErrorPayload(BaseModel):
    error: str
