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

    def __init__(self, portal_url: str, task: str, max_steps: Optional[int] = None,
                 login_portal: Optional[str] = None):
        self.portal_url = portal_url
        self.task = task
        self.max_steps = max_steps or settings.MAX_AGENT_STEPS
        # When set, the run loop watches for mid-flight session expiry on the
        # portal's page and transparently re-logs in via deterministic
        # Playwright (same path the keepalive uses) instead of letting the
        # agent get stuck staring at a login form. The auth helper looks up
        # this key in PORTALS, so it must match a key in portals.auth.PORTALS.
        self.login_portal = login_portal
        self.gemini = GeminiClient()
        self.history: list[dict] = []
        self.extracted: list[dict] = []
        self._sig_counts: dict[str, int] = {}
        self._shot_dir = Path(settings.SCREENSHOT_DIR)
        self._shot_dir.mkdir(parents=True, exist_ok=True)
        self._run_label = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        (self._shot_dir / self._run_label).mkdir(parents=True, exist_ok=True)
        # Cap mid-flight relogin attempts so a portal that keeps logging us
        # out after re-login (broken account, IP block, captcha) doesn't make
        # the agent loop forever — it surfaces as ask_human after this many.
        self._mid_flight_relogin_attempts = 0
        self._mid_flight_relogin_limit = 2

    # ------------------------------------------------------------------ run

    async def run(self, browser: ChromeDebugBrowser) -> dict:
        page = await browser.open_or_focus(self.portal_url)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        for step in range(self.max_steps):
            logger.info(f"[step {step + 1}/{self.max_steps}]  url={page.url[:90]}")

            # 0. Mid-flight session detector — the portal can drop the cookie
            #    between agent steps (idle timeouts on ALLDATA are short).
            #    Without this guard, Gemini would see the login form, get
            #    confused, and burn 4 steps before loop_giveup fired. With it,
            #    we restore the session deterministically on the SAME page and
            #    let the agent retry from a clean state.
            if self.login_portal:
                try:
                    from portals.auth import is_logged_out, restore_session_on_page
                    if await is_logged_out(page, self.login_portal):
                        self._mid_flight_relogin_attempts += 1
                        if self._mid_flight_relogin_attempts > self._mid_flight_relogin_limit:
                            logger.error(f"  mid-flight relogin limit "
                                         f"({self._mid_flight_relogin_limit}) reached — "
                                         f"asking human")
                            self.history.append({
                                "step": step, "action": "ask_human", "element_id": None,
                                "value": "", "confidence": 0.0,
                                "reason": "session kept expiring after re-login attempts",
                                "result": "human_required",
                            })
                            break
                        logger.warning(f"  session expired mid-flight on "
                                       f"{self.login_portal} (attempt "
                                       f"{self._mid_flight_relogin_attempts}/"
                                       f"{self._mid_flight_relogin_limit}); restoring")
                        ok = await restore_session_on_page(page, self.login_portal)
                        if ok:
                            logger.info(f"  mid-flight relogin succeeded; "
                                        f"returning to {self.portal_url}")
                            try:
                                await page.goto(self.portal_url,
                                                wait_until="domcontentloaded",
                                                timeout=30000)
                                await asyncio.sleep(2)
                            except Exception as e:
                                logger.warning(f"  post-relogin nav failed: {e}")
                            # Re-run the same step from the restored state.
                            continue
                        else:
                            logger.error(f"  mid-flight relogin failed; asking human")
                            self.history.append({
                                "step": step, "action": "ask_human", "element_id": None,
                                "value": "", "confidence": 0.0,
                                "reason": f"mid-flight relogin failed on {self.login_portal}",
                                "result": "human_required",
                            })
                            break
                except Exception as e:
                    logger.warning(f"  session detector error (non-fatal): {e}")

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
                # Filter-rescue: before giving up, if the stuck action is a
                # find/scroll for a label, try typing the same value into the
                # first visible text input on the page. ALLDATA's category
                # pages all carry a filter box that no amount of vision
                # prompting reliably steers the model towards; this rescue
                # gives the agent one deterministic shot at it before quit.
                # We only attempt once per stuck signature so this can't
                # itself loop.
                rescue_key = f"rescue:{sig}"
                rescued = False
                if (action in ("find", "scroll") and value
                        and not self._sig_counts.get(rescue_key)):
                    self._sig_counts[rescue_key] = 1
                    needle = str(value).strip()
                    # Use just the first meaningful word — ALLDATA's filter
                    # narrows on substring, and broad keywords ("oil", "brake")
                    # are more forgiving than full labels ("Lubrication System")
                    # that may not appear verbatim on every make's catalogue.
                    first_word = next(
                        (w for w in needle.split() if len(w) > 2 and w.isalpha()),
                        needle,
                    ).lower()[:12]
                    try:
                        filled = await page.evaluate(
                            """(needle) => {
                                const inputs = Array.from(document.querySelectorAll(
                                    'input[type=text], input[type=search], input:not([type]), [role=searchbox], [contenteditable=true]'
                                ));
                                const visible = inputs.filter(el => {
                                    if (el.disabled || el.readOnly) return false;
                                    const r = el.getBoundingClientRect();
                                    if (r.width < 30 || r.height < 10) return false;
                                    const cs = getComputedStyle(el);
                                    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
                                    return true;
                                });
                                if (!visible.length) return false;
                                const el = visible[0];
                                el.focus();
                                const proto = el.tagName === 'TEXTAREA'
                                    ? window.HTMLTextAreaElement.prototype
                                    : window.HTMLInputElement.prototype;
                                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                                if (setter && el.tagName !== 'DIV') setter.call(el, needle);
                                else el.value = needle;
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                                el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
                                el.dispatchEvent(new KeyboardEvent('keyup',   {key: 'Enter', bubbles: true}));
                                return true;
                            }""",
                            first_word,
                        )
                        if filled:
                            rescued = True
                            logger.warning(
                                f"  loop-rescue: typed {first_word!r} into first "
                                f"visible filter input — giving the agent one more "
                                f"chance instead of giving up"
                            )
                            decision["result"] = f"loop_rescue_filter:{first_word}"
                            self.history.append(decision)
                            # Loop-rescue specifically waits a bit longer
                            # (1.2s) than the normal step sleep because
                            # the filter-typing usually triggers an SPA
                            # re-render that needs settle time.
                            await asyncio.sleep(1.2)
                            continue
                    except Exception as e:
                        logger.warning(f"  loop-rescue eval failed: {e}")
                if not rescued:
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
                # Capture the page's visible text at extraction time so the
                # caller can sanity-check the agent's claim against what was
                # actually on screen (cheap defence against vision-model
                # hallucinations — if the claimed "operation: Front Pads" is
                # nowhere in the page text, the extract is suspect). Truncate
                # to keep the run dict small; 8000 chars covers any realistic
                # parts/labor article.
                page_text = ""
                try:
                    page_text = await page.evaluate(
                        "() => (document.body && document.body.innerText) || ''"
                    )
                    if isinstance(page_text, str) and len(page_text) > 8000:
                        page_text = page_text[:8000]
                except Exception as e:
                    logger.warning(f"  page-text snapshot failed: {e}")
                self.extracted.append({
                    "step": step, "data": value, "confidence": conf,
                    "page_text": page_text,
                    # url_at_decision lives on history entries; mirror it
                    # onto extracted entries too so downstream code
                    # (alldata_agent R-cell scan) can find the article
                    # URL without cross-referencing history[step].
                    "url_at_decision": page.url,
                })
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
                # Capture the full error reason so the next Gemini prompt can
                # see WHY the action failed (e.g. "find: no element containing
                # 'Lubrication System'"). Without this, the model only saw the
                # exception class and would happily retry the same broken
                # action 4 times before loop_giveup fired.
                err_text = f"{type(e).__name__}: {str(e)[:200]}"
                logger.error(f"  exec failed: {err_text}")
                decision["result"] = f"error:{err_text}"

            self.history.append(decision)
            # Task #16 — configurable inter-step sleep. Default 0.6s (was
            # hardcoded 1.2s). Most clicks settle in 300-500ms; nav-
            # triggering clicks already have their own wait inside
            # _execute. Halving this default shaves ~5s off a typical
            # 8-step ALLDATA run with no observed reliability loss.
            await asyncio.sleep(getattr(settings, "AGENT_STEP_SLEEP_SEC", 0.6))

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
                # MUI popovers/backdrops sit on top of the page and intercept
                # clicks to underlying buttons. If the intercept message names
                # a Popover/Backdrop, press Escape to dismiss it then retry —
                # otherwise fall through to the JS/mouse fallbacks below.
                if "MuiBackdrop" in str(e1) or "MuiPopover" in str(e1):
                    logger.warning("  click intercepted by popover/backdrop; pressing Escape to dismiss")
                    try:
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(0.4)
                        await locator.click(timeout=4000)
                        await asyncio.sleep(0.6)
                        if page.url != url_before or await self._page_signature(page) != html_sig_before:
                            return
                    except Exception:
                        pass
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
            try:
                await locator.click(timeout=5000)
            except Exception:
                pass
            try:
                await locator.fill("")
                await locator.fill(str(value))
            except Exception as fill_err:
                # Material-UI, Select2 and similar wrappers tag the labelled
                # element to a SPAN/DIV that visually IS the input but is not a
                # real <input> / <textarea> / [contenteditable]. Drill into the
                # wrapper for the nearest real text field and fill it via JS,
                # dispatching `input` + `change` so React/Angular pick it up.
                if "Element is not an <input>" in str(fill_err) or "contenteditable" in str(fill_err):
                    logger.warning(f"  fill rejected wrapper element ({fill_err.__class__.__name__}); "
                                   f"drilling for nested input")
                    filled = await locator.evaluate(
                        """(root, v) => {
                            const find = (r) => {
                                if (!r) return null;
                                if (r.matches && r.matches('input, textarea, [contenteditable]')) return r;
                                if (r.querySelector) {
                                    const sel = r.querySelector('input:not([type=hidden]), textarea, [contenteditable]');
                                    if (sel) return sel;
                                }
                                // Also peek at next siblings — MUI sometimes renders
                                // the visible chip and the real input as siblings.
                                let p = r.parentElement;
                                while (p) {
                                    const sib = p.querySelector('input:not([type=hidden]), textarea, [contenteditable]');
                                    if (sib) return sib;
                                    p = p.parentElement;
                                    if (p && p.matches && p.matches('body,html')) break;
                                }
                                return null;
                            };
                            const el = find(root);
                            if (!el) return false;
                            el.focus();
                            // Use the native setter so React's controlled inputs see it.
                            const proto = el.tagName === 'TEXTAREA'
                                ? window.HTMLTextAreaElement.prototype
                                : window.HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                            if (setter && el.tagName !== 'DIV') setter.call(el, v);
                            else el.value = v;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return true;
                        }""",
                        str(value),
                    )
                    if not filled:
                        raise
                else:
                    raise
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
