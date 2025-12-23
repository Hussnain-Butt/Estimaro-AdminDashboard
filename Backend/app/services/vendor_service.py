"""
Vendor Service - Vendor Comparison and Scoring System

This service handles:
1. Multi-vendor pricing lookup (Worldpac, SSF, etc.)
2. Composite scoring algorithm (Brand, Price, Distance)
3. Primary/Backup vendor selection

Based on the Estimaro Automation Workflow specification.
"""
from typing import Dict, List, Optional
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from enum import Enum
import httpx


class BrandTier(Enum):
    """Brand quality tiers with associated scores"""
    OEM = 10
    PREMIUM = 9
    OE_EQUIVALENT = 8
    STANDARD = 6
    ECONOMY = 4
    UNKNOWN = 5


@dataclass
class VendorOffer:
    """Represents a single vendor's offer for a part"""
    vendor_id: str
    vendor_name: str
    brand: str
    brand_tier: BrandTier
    part_number: str
    price: Decimal
    stock_status: str
    stock_quantity: int
    warehouse_location: str
    warehouse_distance_miles: float
    delivery_option: str
    warranty: str


@dataclass
class ScoredOffer:
    """Vendor offer with calculated scores"""
    offer: VendorOffer
    brand_score: float
    price_score: float
    distance_score: float
    composite_score: float
    selection: str  # "Primary", "Backup", or ""


@dataclass
class VendorWeights:
    """Shop-configurable scoring weights"""
    brand: int = 40
    price: int = 35
    distance: int = 25


class VendorService:
    """Service for vendor comparison and scoring"""

    def __init__(self):
        self.max_distance_miles = 50  # Maximum distance for scoring normalization

    def get_brand_tier(self, brand_name: str, description: str = "") -> BrandTier:
        """
        Determine brand tier from brand name or description.
        
        Args:
            brand_name: The brand name
            description: Optional part description for additional context
            
        Returns:
            BrandTier enum value
        """
        brand_upper = brand_name.upper()
        desc_upper = description.upper()
        
        # OEM brands
        oem_indicators = ['OEM', 'GENUINE', 'ORIGINAL']
        if any(ind in brand_upper or ind in desc_upper for ind in oem_indicators):
            return BrandTier.OEM
        
        # Premium brands
        premium_brands = [
            'BREMBO', 'AKEBONO', 'BOSCH', 'DENSO', 'NGK', 'BILSTEIN',
            'LEMFORDER', 'SACHS', 'CONTINENTAL', 'HELLA', 'VALEO'
        ]
        if any(brand in brand_upper for brand in premium_brands):
            return BrandTier.PREMIUM
        
        # OE Equivalent brands
        oe_equivalent_brands = [
            'ATE', 'MOOG', 'CENTRIC', 'WAGNER', 'BENDIX', 'RAYBESTOS',
            'MOTORCRAFT', 'ACDelco', 'MANN', 'MAHLE'
        ]
        if any(brand in brand_upper for brand in oe_equivalent_brands):
            return BrandTier.OE_EQUIVALENT
        
        # Economy brands
        economy_brands = ['ECONOMY', 'VALUE', 'BUDGET', 'GENERIC']
        if any(brand in brand_upper for brand in economy_brands):
            return BrandTier.ECONOMY
        
        # Default to Standard
        return BrandTier.STANDARD

    def calculate_vendor_score(
        self,
        offer: VendorOffer,
        all_offers: List[VendorOffer],
        weights: VendorWeights
    ) -> ScoredOffer:
        """
        Calculate composite score for a vendor offer.
        
        The scoring algorithm:
        - Brand Score (0-10): Based on brand tier
        - Price Score (0-10): Inverse scale, lower price = higher score
        - Distance Score (0-10): Inverse scale, closer = higher score
        
        Composite = weighted sum normalized to 0-100 scale
        
        Args:
            offer: The vendor offer to score
            all_offers: All offers for price normalization
            weights: Shop-configured scoring weights
            
        Returns:
            ScoredOffer with calculated scores
        """
        # Normalize weights to sum to 100
        total_weight = weights.brand + weights.price + weights.distance
        normalized_brand = (weights.brand / total_weight) * 100
        normalized_price = (weights.price / total_weight) * 100
        normalized_distance = (weights.distance / total_weight) * 100
        
        # Brand score (directly from tier)
        brand_score = float(offer.brand_tier.value)
        
        # Price score (inverse - lower is better)
        prices = [float(o.price) for o in all_offers if o.price > 0]
        if prices:
            max_price = max(prices)
            min_price = min(prices)
            if max_price != min_price:
                price_score = 10 - ((float(offer.price) - min_price) / (max_price - min_price)) * 10
            else:
                price_score = 10  # All same price
        else:
            price_score = 5  # Default if no valid prices
        
        # Distance score (inverse - closer is better)
        distance = offer.warehouse_distance_miles
        distance_score = max(0, 10 - (distance / self.max_distance_miles) * 10)
        
        # Calculate weighted composite score (0-100 scale)
        composite_score = (
            (brand_score * normalized_brand) +
            (price_score * normalized_price) +
            (distance_score * normalized_distance)
        ) / 10
        
        return ScoredOffer(
            offer=offer,
            brand_score=round(brand_score, 1),
            price_score=round(price_score, 1),
            distance_score=round(distance_score, 1),
            composite_score=round(composite_score, 1),
            selection=""  # Will be set after ranking
        )

    def score_and_rank_offers(
        self,
        offers: List[VendorOffer],
        weights: VendorWeights = None
    ) -> List[ScoredOffer]:
        """
        Score all offers and rank them, selecting Primary and Backup.
        
        Args:
            offers: List of vendor offers
            weights: Optional shop-configured weights (uses defaults if not provided)
            
        Returns:
            List of ScoredOffers sorted by composite score, with Primary/Backup marked
        """
        if not offers:
            return []
        
        weights = weights or VendorWeights()
        
        # Score all offers
        scored_offers = [
            self.calculate_vendor_score(offer, offers, weights)
            for offer in offers
        ]
        
        # Sort by composite score descending
        scored_offers.sort(key=lambda x: x.composite_score, reverse=True)
        
        # Mark Primary and Backup
        if len(scored_offers) >= 1:
            scored_offers[0].selection = "Primary"
        if len(scored_offers) >= 2:
            scored_offers[1].selection = "Backup"
        
        return scored_offers

    async def _fetch_vendor_offers(self, part_numbers: List[str]) -> List[VendorOffer]:
        """Fetch offers from all configured vendor adapters"""
        from app.core.config import settings

        adapters = []
        
        # Check for remote adapter type first
        if settings.VENDOR_WORLDPAC_ADAPTER_TYPE == "remote" or settings.VENDOR_SSF_ADAPTER_TYPE == "remote":
            from app.adapters.remote_adapters import RemoteVendorAdapter
            adapters.append(RemoteVendorAdapter())
        else:
            # Use local scrapers
            if settings.VENDOR_WORLDPAC_ADAPTER_TYPE in ["scraper", "real"]:
                from app.adapters.worldpac_scraper_adapter import WorldpacScraperAdapter
                adapters.append(WorldpacScraperAdapter())
            if settings.VENDOR_SSF_ADAPTER_TYPE in ["scraper", "real"]:
                from app.adapters.ssf_scraper_adapter import SSFScraperAdapter
                adapters.append(SSFScraperAdapter())
        
        # If no adapters configured, use remote as fallback for production
        if not adapters:
            from app.adapters.remote_adapters import RemoteVendorAdapter
            adapters.append(RemoteVendorAdapter())

        all_offers = []
        for adapter in adapters:
            results = await adapter.get_prices(part_numbers)
            for res in results:
                # Map VendorPriceResult to VendorOffer
                all_offers.append(VendorOffer(
                    vendor_id=res.vendor_id,
                    vendor_name=res.vendor_name,
                    brand=res.brand,
                    brand_tier=self.get_brand_tier(res.brand),
                    part_number=res.part_number,
                    price=res.price,
                    stock_status=res.stock_status,
                    stock_quantity=res.stock_quantity,
                    warehouse_location=res.warehouse_location,
                    warehouse_distance_miles=res.warehouse_distance_miles,
                    delivery_option=res.delivery_option,
                    warranty=res.warranty
                ))
        return all_offers

    async def compare_vendors(
        self,
        part_numbers: List[str],
        part_descriptions: List[str] = None,
        weights: VendorWeights = None
    ) -> Dict:
        """
        Compare vendors for multiple parts using SCRAPERS.
        """
        if part_descriptions is None:
            part_descriptions = ["" for _ in part_numbers]
        
        weights = weights or VendorWeights()
        
        # Fetch ALL offers for ALL parts in parallel (conceptually)
        # The adapters handle batching or we call per part?
        # My adapters implemented get_prices(List[str]), so we can pass all at once.
        
        all_fetched_offers = await self._fetch_vendor_offers(part_numbers)
        
        results = {
            "success": True,
            "weights": {
                "brand": weights.brand,
                "price": weights.price,
                "distance": weights.distance
            },
            "parts": []
        }
        
        for part_num, part_desc in zip(part_numbers, part_descriptions):
            # Filter offers for this part
            offers = [o for o in all_fetched_offers if o.part_number == part_num]
            
            # Score and rank
            scored_offers = self.score_and_rank_offers(offers, weights)
            
            part_result = {
                "part_number": part_num,
                "description": part_desc,
                "offers": [
                    {
                        "vendor_id": so.offer.vendor_id,
                        "vendor_name": so.offer.vendor_name,
                        "brand": so.offer.brand,
                        "brand_tier": so.offer.brand_tier.name,
                        "price": str(so.offer.price),
                        "stock_status": so.offer.stock_status,
                        "stock_quantity": so.offer.stock_quantity,
                        "warehouse_location": so.offer.warehouse_location,
                        "distance_miles": so.offer.warehouse_distance_miles,
                        "delivery_option": so.offer.delivery_option,
                        "warranty": so.offer.warranty,
                        "scores": {
                            "brand": so.brand_score,
                            "price": so.price_score,
                            "distance": so.distance_score,
                            "composite": so.composite_score
                        },
                        "selection": so.selection
                    }
                    for so in scored_offers
                ],
                "primary": None,
                "backup": None
            }
            
            # Set primary/backup fields
            primary = next((so for so in scored_offers if so.selection == "Primary"), None)
            backup = next((so for so in scored_offers if so.selection == "Backup"), None)
            
            if primary:
                part_result["primary"] = {
                    "vendor": primary.offer.vendor_name,
                    "brand": primary.offer.brand,
                    "price": str(primary.offer.price),
                    "score": primary.composite_score
                }
            if backup:
                part_result["backup"] = {
                    "vendor": backup.offer.vendor_name,
                    "brand": backup.offer.brand,
                    "price": str(backup.offer.price),
                    "score": backup.composite_score
                }
            
            results["parts"].append(part_result)
        
        results["summary"] = {
            "total_parts": len(part_numbers),
            "vendors_queried": ["Worldpac", "SSF"],
            "note": "Live Scraper Data"
        }
        
        return results


# Singleton instance
vendor_service = VendorService()
