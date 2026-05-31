"""Shared scaffolding for portal vision-agents.

`run_portal_agent` drives the existing DOM-aware VisionAgent against one portal
with uniform stability guarantees:
  * hard timeout so a hung site can never wedge the worker
  * session-expiry detection (so the operator knows to re-login via noVNC)
  * single-place JSON extraction + failure classification

Portal modules stay thin: they only build a task prompt and parse the result.
"""
import asyncio
import json as _json
from typing import Optional, Tuple

from loguru import logger

from agents.base_agent import VisionAgent
from core.browser import ChromeDebugBrowser


# Words that, when they show up in the agent's final note, usually mean the
# portal logged us out rather than "data genuinely not found".
SESSION_EXPIRED_HINTS = (
    "log in", "login", "sign in", "signin", "logged out",
    "session expired", "session has expired", "enter your password", "username",
)


def classify_failure(result: dict) -> str:
    """Turn an empty agent run into an actionable, categorised error string."""
    hist = result.get("history") or []
    last_note = str(hist[-1].get("reason")) if hist else ""
    low = last_note.lower()
    if any(k in low for k in SESSION_EXPIRED_HINTS):
        return f"session_expired :: {last_note[:180]}"
    return f"no_extraction :: {last_note[:180] or 'see screenshots for trace'}"


async def run_portal_agent(
    portal_url: str,
    task: str,
    *,
    max_steps: int = 25,
    timeout: int = 300,
    login_portal: Optional[str] = None,
    initial_check: bool = True,
) -> Tuple[Optional[dict], dict]:
    """Drive a vision agent for one portal.

    `login_portal` serves two roles:
      * pre-flight session check (gated by `initial_check`) — set
        initial_check=False when the caller's lookup() has already run
        ensure_logged_in (saves a ~2s CDP round-trip per call).
      * arms the mid-flight session watchdog inside the vision agent so a
        cookie drop during navigation auto-restores the session instead of
        wedging the agent on the login form.

    Returns (raw_extracted_dict | None, meta). `meta` always carries
    `history`, `steps_taken`, `run_dir`; on failure it carries `error`
    (categorised); on success it carries `confidence` and `best_step`.
    """
    if login_portal and initial_check:
        # Imported lazily to avoid any import cycle at module load.
        from portals.auth import ensure_logged_in
        status = await ensure_logged_in(login_portal)
        if not status.get("ok"):
            return None, {"error": f"login_failed :: {status.get('error') or status.get('action')}",
                          "history": [], "steps_taken": 0, "login_status": status}

    # Pass the portal key so the agent can auto-restore the session if it
    # drops mid-flight (same deterministic Playwright login the keepalive
    # uses). When `login_portal` is None this is a no-op — the agent just
    # behaves as before with no session watchdog.
    agent = VisionAgent(portal_url=portal_url, task=task, max_steps=max_steps,
                        login_portal=login_portal)
    try:
        async with ChromeDebugBrowser() as browser:
            result = await asyncio.wait_for(agent.run(browser), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"[{portal_url}] agent timed out after {timeout}s")
        return None, {"error": f"timeout :: agent did not finish within {timeout}s",
                      "history": [], "steps_taken": 0}
    except Exception as e:  # browser/connection failure
        logger.error(f"[{portal_url}] agent crashed: {type(e).__name__}: {e}")
        return None, {"error": f"agent_crash :: {type(e).__name__}: {str(e)[:160]}",
                      "history": [], "steps_taken": 0}

    meta = {
        "history": result.get("history", []),
        "steps_taken": result.get("steps_taken", 0),
        "run_dir": result.get("run_dir"),
        "extracted": result.get("extracted", []),
    }

    if not result.get("extracted"):
        meta["error"] = classify_failure(result)
        logger.warning(f"[{portal_url}] {meta['error']}")
        return None, meta

    best = max(result["extracted"], key=lambda e: e.get("confidence", 0.0))
    raw = best.get("data")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception as e:
            meta["error"] = f"bad_json :: {str(e)[:160]}"
            logger.error(f"[{portal_url}] could not parse agent JSON: {e}")
            return None, meta

    meta["confidence"] = best.get("confidence", 0.0)
    meta["best_step"] = best.get("step")
    return raw, meta
