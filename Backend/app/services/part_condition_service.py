"""
Part Condition Service - CA BAR Compliance

This service detects and discloses whether parts are NEW or REMANUFACTURED
by analyzing vendor descriptions for keywords.

California Bureau of Automotive Repair requires disclosure of part condition.
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class PartCondition(Enum):
    """Part condition types"""
    NEW = "NEW"
    REMANUFACTURED = "REMANUFACTURED"
    UNKNOWN = "UNKNOWN"


class ConditionConfidence(Enum):
    """Confidence level of condition detection"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ConditionResult:
    """Result of part condition detection"""
    condition: PartCondition
    confidence: ConditionConfidence
    matched_keyword: Optional[str]
    display_tag: Optional[str]
    requires_manual_selection: bool
    flag_color: Optional[str]


class PartConditionService:
    """Service for detecting and disclosing part conditions"""
    
    # Keywords indicating REMANUFACTURED parts (higher priority)
    REMAN_KEYWORDS = [
        'REMAN', 'RMN', 'REBUILT', 'REFURB', 'REFURBISHED',
        'CORE CHARGE', 'EXCHANGE', 'RECO', 'RECONDITIONED',
        'REMANUFACTURED', 'RMFD', 'RFB'
    ]
    
    # Keywords indicating NEW parts
    NEW_KEYWORDS = [
        '100% NEW', 'BRAND NEW', 'NEW OEM', 'NEW AFTERMARKET',
        'FACTORY NEW', 'GENUINE NEW'
    ]
    
    def detect_part_condition(self, description: str) -> ConditionResult:
        """
        Analyze part description to determine condition.
        
        Priority:
        1. Check REMAN keywords first (takes priority)
        2. Check explicit NEW keywords
        3. Check for generic "NEW"
        4. Return UNKNOWN if uncertain
        
        Args:
            description: Part description from vendor
            
        Returns:
            ConditionResult with condition and confidence
        """
        if not description:
            return ConditionResult(
                condition=PartCondition.UNKNOWN,
                confidence=ConditionConfidence.LOW,
                matched_keyword=None,
                display_tag=None,
                requires_manual_selection=True,
                flag_color="YELLOW"
            )
        
        desc_upper = description.upper()
        
        # Check REMAN keywords first (priority)
        for keyword in self.REMAN_KEYWORDS:
            if keyword in desc_upper:
                return ConditionResult(
                    condition=PartCondition.REMANUFACTURED,
                    confidence=ConditionConfidence.HIGH,
                    matched_keyword=keyword,
                    display_tag="[REMANUFACTURED]",
                    requires_manual_selection=False,
                    flag_color=None
                )
        
        # Check explicit NEW keywords
        for keyword in self.NEW_KEYWORDS:
            if keyword in desc_upper:
                return ConditionResult(
                    condition=PartCondition.NEW,
                    confidence=ConditionConfidence.HIGH,
                    matched_keyword=keyword,
                    display_tag="[NEW]",
                    requires_manual_selection=False,
                    flag_color=None
                )
        
        # Check for generic "NEW" (common case)
        if 'NEW' in desc_upper:
            return ConditionResult(
                condition=PartCondition.NEW,
                confidence=ConditionConfidence.MEDIUM,
                matched_keyword='NEW',
                display_tag="[NEW]",
                requires_manual_selection=False,
                flag_color=None
            )
        
        # Unknown condition - flag for manual selection
        return ConditionResult(
            condition=PartCondition.UNKNOWN,
            confidence=ConditionConfidence.LOW,
            matched_keyword=None,
            display_tag=None,
            requires_manual_selection=True,
            flag_color="YELLOW"
        )
    
    def process_parts_list(self, parts: List[Dict]) -> Dict:
        """
        Process a list of parts and detect conditions for each.
        
        Args:
            parts: List of part dictionaries with 'description' field
            
        Returns:
            Dict with processed parts and summary
        """
        processed_parts = []
        auto_detected = 0
        requires_review = 0
        
        for part in parts:
            description = part.get("description", "") or ""
            manufacturer = part.get("manufacturer", "") or ""
            
            # Combine description and manufacturer for better detection
            full_description = f"{description} {manufacturer}"
            
            result = self.detect_part_condition(full_description)
            
            processed_part = {
                **part,
                "condition": {
                    "detected": result.condition.value,
                    "confidence": result.confidence.value,
                    "matched_keyword": result.matched_keyword,
                    "display_tag": result.display_tag,
                    "requires_manual_selection": result.requires_manual_selection,
                    "flag_color": result.flag_color
                }
            }
            
            # Build display string with condition
            if result.display_tag:
                processed_part["display_description"] = f"{description} - {result.display_tag}"
            else:
                processed_part["display_description"] = description
            
            processed_parts.append(processed_part)
            
            if result.requires_manual_selection:
                requires_review += 1
            else:
                auto_detected += 1
        
        return {
            "success": True,
            "parts": processed_parts,
            "summary": {
                "total_parts": len(parts),
                "auto_detected": auto_detected,
                "requires_review": requires_review
            },
            "has_unknown_conditions": requires_review > 0,
            "flag": {
                "type": "YELLOW",
                "title": "⚠️ MANUAL SELECTION REQUIRED",
                "message": f"{requires_review} part(s) need condition selection (NEW or REMANUFACTURED)",
                "action": "Select condition for flagged parts before sending to customer"
            } if requires_review > 0 else None
        }


# Singleton instance
part_condition_service = PartConditionService()
