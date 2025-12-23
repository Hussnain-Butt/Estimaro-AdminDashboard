"""
Parts Service - Factory Pattern

Service that selects the appropriate parts adapter based on configuration.
Allows easy switching between mock, scraper, and remote implementations.
"""
from app.adapters.parts_adapter_interface import PartsAdapterInterface
from app.adapters.parts_mock_adapter import PartsMockAdapter
from app.core.config import settings


def get_parts_adapter() -> PartsAdapterInterface:
    """
    Factory function to get the appropriate parts adapter.
    
    Returns:
        Parts adapter instance based on configuration
    """
    adapter_type = settings.PARTS_ADAPTER_TYPE
    
    if adapter_type == "mock":
        return PartsMockAdapter()
    elif adapter_type == "scraper" or adapter_type == "partslink":
        from app.adapters.partslink_scraper_adapter import PartsLinkScraperAdapter
        return PartsLinkScraperAdapter()
    elif adapter_type == "remote":
        from app.adapters.remote_adapters import RemotePartsAdapter
        return RemotePartsAdapter()
    else:
        raise ValueError(f"Unknown parts adapter type: {adapter_type}")


# Singleton instance
parts_service = get_parts_adapter()

