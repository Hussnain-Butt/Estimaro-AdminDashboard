"""DOM-aware vision agent.

Differences vs. the prior implementation:
- Every step annotates the DOM with numbered overlays and passes both the
  screenshot AND the structured element list to Gemini.
- Gemini picks element IDs, never invents selectors.
- Loop detection: same (action, element_id, value) twice → warn the model;
  three times → switch to ask_human.
- Per-action robust execution: scroll-into-view, retry once, then mark failed.
- After every action, we wait a deterministic amount and re-annotate.
"""
import asyncio
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
from playwright.async_api import Page, ElementHandle
from loguru import logger

from config import settings
from core.browser import ChromeDebugBrowser
from core.gemini_client import GeminiClient
from core.dom import annotated_screenshot, format_elements_for_prompt, clear as clear_overlay


def _action_signature(decision: dict, url: str = "") -> str:
    """Normalise an action into a comparable string for loop detection.
    URL is included so that the same scroll/click on a NEW page is not
    treated as a repeat."""
    val = decision.get("value", "")
    if isinstance(val, str):
        val = val.strip().lower()[:40]
    url_key = url.split("?")[0].split("#")[-1][:60]  # use the SPA route key
    return f"{url_key}::{decision.get('action','')}|{decision.get('element_id','')}|{val}"


class VisionAgent:
    """Loop: annotate-DOM -> screenshot -> Gemini picks id -> execute -> repeat."""

    def __init__(self, portal_url: str, task: str, max_steps: Optional[int] = None):
        self.portal_url = portal_url
        self.task = task
        self.max_steps = max_steps or settings.MAX_AGENT_STEPS
        self.gemini = GeminiClient()
        self.history: list[dict] = []
        self.extracted: list[dict] = []
        self._sig_counts: dict[str, int] = {}
        self._shot_dir = Path(settings.SCREENSHOT_DIR)
        self._shot_dir.mkdir(parents=True, exist_ok=True)
        self._run_label = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        (self._shot_dir / self._run_label).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ run

    async def run(self, browser: ChromeDebugBrowser) -> dict:
        page = await browser.open_or_focus(self.portal_url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        for step in range(self.max_steps):
            logger.info(f"[step {step + 1}/{self.max_steps}]  url={page.url[:90]}")

            # 1. Annotate DOM + screenshot
            try:
                elements, shot_bytes = await annotated_screenshot(page)
            except Exception as e:
                logger.error(f"  annotate failed: {e}")
                elements, shot_bytes = [], await page.screenshot()

            shot_path = self._shot_dir / self._run_label / f"step{step:02d}.png"
            shot_path.write_bytes(shot_bytes)
            elements_text = format_elements_for_prompt(elements)

            # 2. Build repeat warning (loop detection feedback for the model)
            repeat_warning = None
            if self.history:
                last_sig = _action_signature(self.history[-1], self.history[-1].get("url_at_decision", ""))
                if self._sig_counts.get(last_sig, 0) >= 2:
                    repeat_warning = (
                        f"You repeated the same action ({last_sig.split('::',1)[-1]}) "
                        f"{self._sig_counts[last_sig]} times on this page. Try a DIFFERENT element or strategy."
                    )

            # 3. Ask Gemini
            decision = self.gemini.decide(
                screenshot_bytes=shot_bytes,
                task=self.task,
                elements_text=elements_text,
                history=self.history,
                current_url=page.url,
                repeat_warning=repeat_warning,
            )
            decision["step"] = step
            decision["screenshot"] = str(shot_path)
            decision["url_at_decision"] = page.url

            action = decision.get("action", "ask_human")
            eid = decision.get("element_id")
            value = decision.get("value", "")
            reason = decision.get("reason", "")
            conf = decision.get("confidence", 0.0)
            logger.info(f"  action={action} id={eid} value={str(value)[:50]!r} conf={conf:.2f} :: {reason[:120]}")

            # 4. Loop detection (hard stop)
            sig = _action_signature(decision, page.url)
            self._sig_counts[sig] = self._sig_counts.get(sig, 0) + 1
            if self._sig_counts[sig] >= 4:
                logger.warning(f"  same action repeated 4x → giving up")
                decision["result"] = "loop_giveup"
                self.history.append(decision)
                break

            # 5. Terminal actions
            if action == "done":
                decision["result"] = "ok"
                self.history.append(decision)
                break
            if action == "ask_human":
                logger.warning(f"  ask_human: {reason}")
                decision["result"] = "human_required"
                self.history.append(decision)
                break
            if action == "extract":
                self.extracted.append({"step": step, "data": value, "confidence": conf})
                decision["result"] = "extracted"
                self.history.append(decision)
                # Auto-finalize if we got a high-confidence extraction
                if conf >= 0.85:
                    logger.info(f"  high-confidence extract → auto-done")
                    break
                continue

            # 6. Execute non-terminal action
            try:
                await self._execute(page, decision, elements)
                decision["result"] = "ok"
            except Exception as e:
                logger.error(f"  exec failed: {type(e).__name__}: {str(e)[:140]}")
                decision["result"] = f"error:{type(e).__name__}"

            self.history.append(decision)
            await asyncio.sleep(1.2)

        return {
            "task": self.task,
            "steps_taken": len(self.history),
            "extracted": self.extracted,
            "history": self.history,
            "completed": self.history[-1].get("action") == "done" if self.history else False,
            "run_dir": str(self._shot_dir / self._run_label),
        }

    # -------------------------------------------------------------- execute

    async def _execute(self, page: Page, decision: dict, elements: list[dict]):
        action = decision["action"]
        eid = decision.get("element_id")
        value = decision.get("value", "")

        if action == "navigate":
            url = value or ""
            if not url.startswith("http"):
                raise ValueError(f"navigate requires absolute URL, got: {url!r}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return

        if action == "wait":
            await asyncio.sleep(2.0)
            return

        if action == "find":
            # Scroll the best-matching (shortest) element whose text contains
            # `value` into view, so the next annotation gives it an id to click.
            needle = str(value or "").strip()
            if not needle:
                raise ValueError("find requires text in value")
            found = await page.evaluate(
                """(needle) => {
                    const lc = needle.toLowerCase();
                    const els = Array.from(document.querySelectorAll(
                        'a,button,li,tr,td,th,div,span,label,option,[role]'));
                    let best = null, bestLen = 1e9;
                    for (const el of els) {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (!t) continue;
                        if (t.toLowerCase().includes(lc) && t.length < bestLen) {
                            best = el; bestLen = t.length;
                        }
                    }
                    if (best) { best.scrollIntoView({block: 'center', inline: 'center'}); return true; }
                    return false;
                }""",
                needle,
            )
            if not found:
                raise ValueError(f"find: no element containing {needle!r}")
            await asyncio.sleep(0.6)
            return

        if action == "scroll":
            v = str(value or "down").lower()
            if v.startswith("to_element:"):
                try:
                    target_id = int(v.split(":", 1)[1])
                    loc = self._locator_for_id(page, target_id)
                    await loc.scroll_into_view_if_needed(timeout=5000)
                except Exception as e:
                    logger.warning(f"  scroll to_element failed: {e}, falling back to page scroll")
                    await page.evaluate("window.scrollBy(0, 600)")
            elif "up" in v:
                await page.evaluate("window.scrollBy(0, -600)")
            else:
                await page.evaluate("window.scrollBy(0, 600)")
            return

        if eid is None or eid < 0 or eid >= len(elements):
            raise ValueError(f"action={action} but element_id={eid} is out of range (0..{len(elements)-1})")

        locator = self._locator_for_id(page, eid)

        if action == "click":
            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            url_before = page.url
            html_sig_before = await self._page_signature(page)
            # Strategy 1: standard click
            try:
                await locator.click(timeout=6000)
            except Exception as e1:
                logger.warning(f"  std click failed: {e1}, trying JS click")
                try:
                    await locator.evaluate("el => el.click()")
                except Exception as e2:
                    logger.warning(f"  JS click failed: {e2}, trying mouse click")
                    box = await locator.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["w"]/2, box["y"] + box["h"]/2)
                    else:
                        raise
            # If page didn't change at all (no URL change, no DOM change), try escalated click
            await asyncio.sleep(0.8)
            if page.url == url_before:
                html_sig_after = await self._page_signature(page)
                if html_sig_after == html_sig_before:
                    logger.warning("  click had no effect, dispatching click event + child <a>")
                    try:
                        await locator.evaluate("""el => {
                            const e = new MouseEvent('click', {bubbles: true, cancelable: true, view: window});
                            el.dispatchEvent(e);
                            const a = el.querySelector('a, [role=link], button');
                            if (a) a.click();
                        }""")
                    except Exception:
                        pass

        elif action == "type":
            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            await locator.click(timeout=5000)
            await locator.fill("")
            await locator.fill(str(value))
            # Trigger react/angular onChange via blur
            try:
                await locator.press("Tab")
            except Exception:
                pass

        elif action == "select_option":
            try:
                await locator.select_option(label=str(value))
            except Exception:
                # Fallback: open + click option text
                await locator.click()
                await page.get_by_text(str(value), exact=False).first.click(timeout=5000)

        else:
            raise ValueError(f"unknown action: {action}")

    def _locator_for_id(self, page: Page, eid: int):
        return page.locator(f"[data-agent-id=\"{eid}\"]").first

    async def _page_signature(self, page: Page) -> str:
        """Rough fingerprint of page state to detect 'click had no effect'."""
        try:
            return await page.evaluate(
                "() => (document.title + '|' + location.href + '|' + (document.body && document.body.innerText.length))"
            )
        except Exception:
            return page.url
