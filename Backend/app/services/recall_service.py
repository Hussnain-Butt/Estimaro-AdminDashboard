"""
Recall Service - NHTSA Recall Check Integration

This service checks for open recalls using the NHTSA API
and matches them against the customer's complaint description.

Safety-critical feature: Flags vehicles with potential recall matches.
"""
from typing import Dict, List, Optional
from dataclasses import dataclass
import httpx
import asyncio


@dataclass
class RecallInfo:
    """Information about a single recall"""
    campaign_number: str
    manufacturer: str
    component: str
    summary: str
    consequence: str
    remedy: str


class RecallService:
    """Service for checking NHTSA recalls"""
    
    NHTSA_API_BASE = "https://api.nhtsa.gov/recalls/recallsByVehicle"
    
    def __init__(self):
        self.timeout = 10.0  # seconds
    
    async def fetch_recalls_by_vin(self, vin: str) -> List[RecallInfo]:
        """
        Fetch open recalls for a vehicle from NHTSA API.
        
        Args:
            vin: 17-character Vehicle Identification Number
            
        Returns:
            List of RecallInfo objects
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.NHTSA_API_BASE,
                    params={"vin": vin}
                )
                
                if response.status_code != 200:
                    return []
                
                data = response.json()
                recalls = []
                
                for result in data.get("results", []):
                    recalls.append(RecallInfo(
                        campaign_number=result.get("NHTSACampaignNumber", ""),
                        manufacturer=result.get("Manufacturer", ""),
                        component=result.get("Component", ""),
                        summary=result.get("Summary", ""),
                        consequence=result.get("Consequence", ""),
                        remedy=result.get("Remedy", "")
                    ))
                
                return recalls
                
        except Exception as e:
            print(f"NHTSA API error: {e}")
            return []
    
    def match_complaint_to_recalls(
        self,
        complaint: str,
        recalls: List[RecallInfo]
    ) -> List[RecallInfo]:
        """
        Check if customer complaint matches any open recalls.
        
        Uses keyword matching between complaint and recall components/summaries.
        
        Args:
            complaint: Customer's service request/complaint
            recalls: List of open recalls for the vehicle
            
        Returns:
            List of matching recalls
        """
        if not complaint or not recalls:
            return []
        
        complaint_lower = complaint.lower()
        
        # Extract keywords from complaint
        complaint_keywords = set(complaint_lower.split())
        
        # Common automotive component keywords to match
        component_mappings = {
            'brake': ['brake', 'braking', 'abs', 'stopping'],
            'fuel': ['fuel', 'gas', 'gasoline', 'leak', 'smell'],
            'engine': ['engine', 'motor', 'stall', 'power'],
            'steering': ['steering', 'wheel', 'turn', 'handling'],
            'airbag': ['airbag', 'air bag', 'srs', 'safety'],
            'electrical': ['electrical', 'battery', 'short', 'fire'],
            'transmission': ['transmission', 'gear', 'shift'],
            'suspension': ['suspension', 'shock', 'strut'],
            'tire': ['tire', 'wheel', 'tyre'],
            'cooling': ['coolant', 'radiator', 'overheat', 'temperature']
        }
        
        # Find which component categories the complaint mentions
        complaint_categories = set()
        for category, keywords in component_mappings.items():
            if any(kw in complaint_lower for kw in keywords):
                complaint_categories.add(category)
        
        matching_recalls = []
        
        for recall in recalls:
            recall_text = f"{recall.component} {recall.summary}".lower()
            
            # Check if any complaint category matches the recall
            for category, keywords in component_mappings.items():
                if category in complaint_categories:
                    if any(kw in recall_text for kw in keywords):
                        matching_recalls.append(recall)
                        break
        
        return matching_recalls
    
    async def check_recalls(
        self,
        vin: str,
        complaint_description: str
    ) -> Dict:
        """
        Check for recalls and match against customer complaint.
        
        This is the main method called by auto_generate_service.
        
        Args:
            vin: Vehicle VIN
            complaint_description: Customer's service request
            
        Returns:
            Dict with recall check results and any flags
        """
        result = {
            "success": True,
            "has_open_recalls": False,
            "has_matching_recall": False,
            "open_recalls_count": 0,
            "matching_recalls_count": 0,
            "all_recalls": [],
            "matching_recalls": [],
            "flag": None
        }
        
        # Fetch recalls from NHTSA
        recalls = await self.fetch_recalls_by_vin(vin)
        
        result["has_open_recalls"] = len(recalls) > 0
        result["open_recalls_count"] = len(recalls)
        result["all_recalls"] = [
            {
                "campaign_number": r.campaign_number,
                "manufacturer": r.manufacturer,
                "component": r.component,
                "summary": r.summary[:200] + "..." if len(r.summary) > 200 else r.summary,
                "consequence": r.consequence[:200] + "..." if len(r.consequence) > 200 else r.consequence,
                "remedy": r.remedy[:200] + "..." if len(r.remedy) > 200 else r.remedy
            }
            for r in recalls
        ]
        
        # Check for matching recalls
        matching = self.match_complaint_to_recalls(complaint_description, recalls)
        
        if matching:
            result["has_matching_recall"] = True
            result["matching_recalls_count"] = len(matching)
            result["matching_recalls"] = [
                {
                    "campaign_number": r.campaign_number,
                    "component": r.component,
                    "summary": r.summary[:200] + "..." if len(r.summary) > 200 else r.summary
                }
                for r in matching
            ]
            
            # RED FLAG - recall matches customer complaint
            result["flag"] = {
                "type": "RED",
                "title": "⚠️ RECALL ALERT",
                "message": f"Possible recall match detected! Campaign: {matching[0].campaign_number}",
                "action": "Verify with dealer - customer may get FREE repair under recall",
                "details": matching[0].summary[:150] + "..." if len(matching[0].summary) > 150 else matching[0].summary
            }
        
        return result


# Singleton instance
recall_service = RecallService()
