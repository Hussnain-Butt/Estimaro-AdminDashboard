"""Gemini Flash client - vision + DOM-aware reasoning for browser navigation."""
import json
from pathlib import Path
from typing import Optional
import google.generativeai as genai
from loguru import logger

from config import settings


class GeminiClient:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY missing in .env")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(model_name)
        self.model_name = model_name

    def decide(
        self,
        screenshot_bytes: bytes,
        task: str,
        elements_text: str,
        history: list[dict],
        current_url: str = "",
        repeat_warning: Optional[str] = None,
    ) -> dict:
        """DOM-aware action picker.
        elements_text: numbered list of visible interactive elements (from core.dom)
        Returns: {action, element_id?, value?, reason, confidence}
        """
        # When an action errored, the full reason is now stored in `result`
        # (e.g. "error:ValueError: find: no element containing 'X'"). Keep
        # enough of it so the model can adapt rather than retry the same
        # broken action.
        history_text = "\n".join([
            f"  step {h.get('step','?')}: {h.get('action','?')} id={h.get('element_id','?')} "
            f"value={str(h.get('value',''))[:40]!r} -> {str(h.get('result','?'))[:180]}"
            for h in history[-6:]
        ]) or "  (none)"

        warn = f"\n!!! {repeat_warning} !!!\n" if repeat_warning else ""

        prompt = f"""You are a browser-automation reasoning agent. The screenshot below shows the
current page with RED numbered overlays drawn on every clickable / fillable element.

Each red number in the image corresponds to an "element_id" you can target.

CURRENT URL: {current_url}

TASK:
{task}

RECENT ACTIONS (oldest first):
{history_text}
{warn}
VISIBLE INTERACTIVE ELEMENTS (#id <tag attrs> text):
{elements_text}

Decide the SINGLE next action. Reply with ONLY JSON (no markdown):

{{
  "action":     "click" | "type" | "select_option" | "scroll" | "find" | "navigate" | "wait" | "extract" | "done" | "ask_human",
  "element_id": <integer id from the list, or null if action is navigate/wait/scroll/find/done/ask_human>,
  "value":      "<text to type, URL to navigate, option label to select, text to find, or extracted JSON>",
  "reason":     "<one short sentence>",
  "confidence": 0.0
}}

RULES:
1. To click/type, pick an element_id from the list above. Do NOT invent CSS selectors.
2. To type into a field, use action="type" with element_id pointing to the input.
3. To select from a dropdown <select>, use action="select_option" with element_id of the <select>
   and value as the visible option text.
4. To scroll, use action="scroll" with value="up"|"down"|"to_element:<id>".
4b. If an item you need (e.g. a specific row/label/option like "Brake Pad Set") is
    NOT in the visible elements list because it is further down a long list, use
    action="find" with value set to that item's exact visible text. This jumps it
    into view so it appears in the next list with an id — then click it. Prefer
    "find" over scrolling blindly multiple times.
5. To extract data, use action="extract" with value as a JSON string of fields found.
6. action="done" only when the full task is complete.
7. action="ask_human" if blocked by captcha, login, error, or the page is wrong.
8. If you tried the same action 2+ times already, CHANGE STRATEGY (different element, scroll, navigate).
8b. If a prior step's result begins with "error:", READ the error message — repeating the
    exact same action will fail the exact same way. In particular:
      - "find: no element containing X" means the text isn't on this page. Do NOT
        retry find with the same text. Either scroll, navigate to a different
        page that should contain X, or pick a different target.
      - "Timeout" / "intercepts pointer events" means another element was on top.
        Try scrolling the target into view first, or clicking the intercepting
        element first to dismiss it.
9. Confidence should reflect uncertainty in vehicle/operation match (0.0-1.0).
"""

        image_part = {"mime_type": "image/png", "data": screenshot_bytes}

        try:
            response = self.model.generate_content(
                [prompt, image_part],
                generation_config={
                    "temperature": 0.15,
                    "response_mime_type": "application/json",
                },
            )
            data = json.loads(response.text)
            # Normalise
            if "element_id" in data and data["element_id"] is not None:
                try:
                    data["element_id"] = int(data["element_id"])
                except (TypeError, ValueError):
                    data["element_id"] = None
            return data
        except Exception as e:
            logger.error(f"Gemini decide failed: {e}")
            return {"action": "ask_human", "reason": str(e), "confidence": 0.0, "element_id": None}

    def extract_from_screenshot(self, screenshot_bytes: bytes, fields: list[str]) -> dict:
        """Pure extraction - given a page screenshot, pull specific fields."""
        prompt = f"""Extract the following fields from this screenshot. Return JSON only.
Fields needed: {fields}
If a field is not visible, set its value to null. Return JSON object keyed by field name."""

        image_part = {"mime_type": "image/png", "data": screenshot_bytes}
        try:
            response = self.model.generate_content(
                [prompt, image_part],
                generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini extract failed: {e}")
            return {}


if __name__ == "__main__":
    print("Testing Gemini client...")
    client = GeminiClient()
    print(f"Model: {client.model_name}")
    print(f"API key configured: {bool(settings.GEMINI_API_KEY)}")
