"""
Calculation Service - The "Brain" of the Estimation System

This service handles all financial calculations for estimates:
- Labor cost calculation
- Parts cost with markup
- Service Cleaning Kits (replaces shop fees)
- Tax calculation
- Total computation

Uses Decimal for precision to avoid floating-point errors.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional
from app.schemas.estimate import (
    LaborItemSchema,
    PartItemSchema,
    CalculationBreakdownSchema,
    CleaningKitSchema
)
from app.core.config import settings


# Service Cleaning Kits - replaces shop fees with transparent pricing
CLEANING_KITS = {
    'brake_service': {
        'name': 'Brake Service Cleaning Kit',
        'includes': ['Brake cleaner', 'Caliper grease', 'Disposable gloves'],
        'price': Decimal('15.00')
    },
    'engine_repair': {
        'name': 'Engine Service Cleaning Kit',
        'includes': ['Degreaser', 'Shop towels', 'Oil absorbent'],
        'price': Decimal('20.00')
    },
    'ac_service': {
        'name': 'AC Service Cleaning Kit',
        'includes': ['UV dye', 'Leak sealant', 'O-ring lubricant'],
        'price': Decimal('18.00')
    },
    'transmission': {
        'name': 'Transmission Service Cleaning Kit',
        'includes': ['Fluid funnel', 'Shop towels', 'Spill mat'],
        'price': Decimal('16.00')
    },
    'suspension': {
        'name': 'Suspension Service Cleaning Kit',
        'includes': ['Penetrating oil', 'Shop towels', 'Grease'],
        'price': Decimal('14.00')
    },
    'general': {
        'name': 'General Service Cleaning Kit',
        'includes': ['All-purpose cleaner', 'Shop towels'],
        'price': Decimal('12.00')
    }
}


class CalculationService:
    """Service for estimate calculations with precise decimal arithmetic"""
    
    def __init__(self, tax_rate: Decimal = None):
        """
        Initialize calculation service.
        
        Args:
            tax_rate: Tax rate as decimal (0.08 = 8%). Defaults to settings value.
        """
        self.tax_rate = tax_rate or Decimal(str(settings.DEFAULT_TAX_RATE))
    
    def get_cleaning_kit(self, job_type: str) -> Dict:
        """
        Get appropriate cleaning kit for job type.
        
        Args:
            job_type: Type of job (brake_service, engine_repair, etc.)
            
        Returns:
            Cleaning kit dictionary with name, includes, and price
        """
        return CLEANING_KITS.get(job_type, CLEANING_KITS['general'])
    
    def calculate_labor_total(self, labor_items: List[LaborItemSchema]) -> Decimal:
        """
        Calculate total labor cost.
        
        Formula: Σ(hours × rate)
        
        Args:
            labor_items: List of labor items
            
        Returns:
            Total labor cost
        """
        total = Decimal("0")
        for item in labor_items:
            item_total = Decimal(str(item.hours)) * Decimal(str(item.rate))
            total += item_total
        
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def calculate_parts_total(self, parts_items: List[PartItemSchema]) -> Decimal:
        """
        Calculate total parts cost with markup.
        
        Formula: Σ((cost × quantity) × (1 + markup/100))
        
        Args:
            parts_items: List of parts items
            
        Returns:
            Total parts cost including markup
        """
        total = Decimal("0")
        for item in parts_items:
            cost = Decimal(str(item.cost))
            quantity = Decimal(str(item.quantity))
            markup = Decimal(str(item.markup))
            
            # Calculate base cost
            base_cost = cost * quantity
            
            # Apply markup
            markup_multiplier = Decimal("1") + (markup / Decimal("100"))
            item_total = base_cost * markup_multiplier
            
            total += item_total
        
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def calculate_estimate(
        self,
        labor_items: List[LaborItemSchema],
        parts_items: List[PartItemSchema],
        job_type: str = "general",
        tax_rate: Decimal = None,
        include_cleaning_kit: bool = True
    ) -> CalculationBreakdownSchema:
        """
        Calculate complete estimate breakdown with cleaning kit.
        
        This is the main calculation method that computes:
        1. Labor total
        2. Parts total
        3. Subtotal (labor + parts)
        4. Tax amount
        5. Cleaning kit (replaces shop fees)
        6. Grand total
        
        Args:
            labor_items: List of labor items
            parts_items: List of parts items
            job_type: Type of job for cleaning kit selection
            tax_rate: Optional tax rate override
            include_cleaning_kit: Whether to include cleaning kit
            
        Returns:
            Complete calculation breakdown
        """
        # Use provided tax rate or instance default
        effective_tax_rate = tax_rate or self.tax_rate
        if isinstance(effective_tax_rate, str):
            effective_tax_rate = Decimal(effective_tax_rate)
        
        # Calculate component totals
        labor_total = self.calculate_labor_total(labor_items)
        parts_total = self.calculate_parts_total(parts_items)
        
        # Calculate subtotal (labor + parts)
        subtotal = labor_total + parts_total
        
        # Calculate tax on subtotal
        tax_amount = (subtotal * effective_tax_rate).quantize(
            Decimal("0.01"), 
            rounding=ROUND_HALF_UP
        )
        
        # Get cleaning kit
        cleaning_kit_data = None
        cleaning_kit_price = Decimal("0")
        
        if include_cleaning_kit:
            kit = self.get_cleaning_kit(job_type)
            cleaning_kit_price = kit['price']
            cleaning_kit_data = {
                "name": kit['name'],
                "includes": kit['includes'],
                "price": str(cleaning_kit_price)
            }
        
        # Calculate grand total (subtotal + tax + cleaning kit)
        total = subtotal + tax_amount + cleaning_kit_price
        
        return CalculationBreakdownSchema(
            laborTotal=labor_total,
            partsTotal=parts_total,
            subtotal=subtotal,
            taxAmount=tax_amount,
            cleaningKit=cleaning_kit_data,
            total=total
        )
    
    def recalculate_item_totals(
        self,
        labor_items: List[LaborItemSchema],
        parts_items: List[PartItemSchema]
    ) -> Dict[str, List]:
        """
        Recalculate individual item totals to ensure consistency.
        
        This is useful when items are created/updated and we need to
        ensure the 'total' field matches the calculation.
        
        Args:
            labor_items: List of labor items
            parts_items: List of parts items
            
        Returns:
            Dictionary with updated labor and parts items
        """
        # Recalculate labor item totals
        updated_labor = []
        for item in labor_items:
            item_total = (
                Decimal(str(item.hours)) * Decimal(str(item.rate))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            updated_item = item.model_copy(update={"total": item_total})
            updated_labor.append(updated_item)
        
        # Recalculate parts item totals
        updated_parts = []
        for item in parts_items:
            cost = Decimal(str(item.cost))
            quantity = Decimal(str(item.quantity))
            markup = Decimal(str(item.markup))
            
            base_cost = cost * quantity
            markup_multiplier = Decimal("1") + (markup / Decimal("100"))
            item_total = (base_cost * markup_multiplier).quantize(
                Decimal("0.01"), 
                rounding=ROUND_HALF_UP
            )
            
            updated_item = item.model_copy(update={"total": item_total})
            updated_parts.append(updated_item)
        
        return {
            "laborItems": updated_labor,
            "partsItems": updated_parts
        }


# Singleton instance for easy import
calculation_service = CalculationService()
