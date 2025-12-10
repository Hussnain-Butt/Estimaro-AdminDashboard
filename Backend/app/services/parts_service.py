"""
Parts Service - Factory Pattern

Service that selects the appropriate parts adapter based on configuration.
Allows easy switching between mock and real (PartsLink24) implementations.
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
    elif adapter_type == "partslink":
        # TODO: Implement PartsLink24 adapter when API keys are available
        # from app.adapters.parts_partslink_adapter import PartsPartsLinkAdapter
        # return PartsPartsLinkAdapter()
        raise NotImplementedError("PartsLink24 adapter not yet implemented")
    else:
        raise ValueError(f"Unknown parts adapter type: {adapter_type}")


# Singleton instance
parts_service = get_parts_adapter()
