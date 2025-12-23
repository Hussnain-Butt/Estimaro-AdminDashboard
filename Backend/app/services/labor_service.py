"""
Labor Service - Factory Pattern

Service that selects the appropriate labor adapter based on configuration.
Allows easy switching between mock, scraper, and remote implementations.
"""
from app.adapters.labor_adapter_interface import LaborAdapterInterface
from app.adapters.labor_mock_adapter import LaborMockAdapter
from app.core.config import settings


def get_labor_adapter() -> LaborAdapterInterface:
    """
    Factory function to get the appropriate labor adapter.
    
    Returns:
        Labor adapter instance based on configuration
    """
    adapter_type = settings.LABOR_ADAPTER_TYPE
    
    if adapter_type == "mock":
        return LaborMockAdapter()
    elif adapter_type == "scraper" or adapter_type == "alldata":
        from app.adapters.alldata_scraper_adapter import AlldataScraperAdapter
        return AlldataScraperAdapter()
    elif adapter_type == "remote":
        from app.adapters.remote_adapters import RemoteLaborAdapter
        return RemoteLaborAdapter()
    else:
        raise ValueError(f"Unknown labor adapter type: {adapter_type}")


# Singleton instance
labor_service = get_labor_adapter()

