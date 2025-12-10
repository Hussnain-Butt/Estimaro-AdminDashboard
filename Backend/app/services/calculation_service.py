"""
Calculation Service - The "Brain" of the Estimation System

This service handles all financial calculations for estimates:
- Labor cost calculation
- Parts cost with markup
- Tax calculation
- Total computation

Uses Decimal for precision to avoid floating-point errors.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict
from app.schemas.estimate import (
    LaborItemSchema,
    PartItemSchema,
    CalculationBreakdownSchema
)
from app.core.config import settings


class CalculationService:
    """Service for estimate calculations with precise decimal arithmetic"""
    
    def __init__(self, tax_rate: Decimal = None):
        """
        Initialize calculation service.
        
        Args:
            tax_rate: Tax rate as decimal (0.08 = 8%). Defaults to settings value.
        """
        self.tax_rate = tax_rate or Decimal(str(settings.DEFAULT_TAX_RATE))
    
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
        tax_rate: Decimal = None
    ) -> CalculationBreakdownSchema:
        """
        Calculate complete estimate breakdown.
        
        This is the main calculation method that computes:
        1. Labor total
        2. Parts total
        3. Subtotal (labor + parts)
        4. Tax amount
        5. Grand total
        
        Args:
            labor_items: List of labor items
            parts_items: List of parts items
            tax_rate: Optional tax rate override
            
        Returns:
            Complete calculation breakdown
        """
        # Use provided tax rate or instance default
        effective_tax_rate = tax_rate or self.tax_rate
        
        # Calculate component totals
        labor_total = self.calculate_labor_total(labor_items)
        parts_total = self.calculate_parts_total(parts_items)
        
        # Calculate subtotal
        subtotal = labor_total + parts_total
        
        # Calculate tax
        tax_amount = (subtotal * effective_tax_rate).quantize(
            Decimal("0.01"), 
            rounding=ROUND_HALF_UP
        )
        
        # Calculate grand total
        total = subtotal + tax_amount
        
        return CalculationBreakdownSchema(
            laborTotal=labor_total,
            partsTotal=parts_total,
            subtotal=subtotal,
            taxAmount=tax_amount,
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
