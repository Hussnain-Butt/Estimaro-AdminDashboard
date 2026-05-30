"""Pluggable portal vision-agents.

Each portal module exposes a small, uniform surface so the worker can drive
any of them the same way:

    PORTAL_NAME : str
    PORTAL_URL  : str
    async def lookup(...) -> (domain_result | None, meta: dict)

Shared scaffolding (browser drive, timeout, session-expiry detection,
JSON extraction) lives in `portals.base` so each portal file only contains
the parts that are genuinely portal-specific: the task prompt and the parse.
"""
