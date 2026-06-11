"""Tekmetric Job Board scraper — Historical RO mining, Phase A.

GOAL (Phase A pilot):
  Sergio has 1000+ past Tekmetric Repair Orders he built by hand. Each one is
  ground-truth correct (he approved it, the customer paid). We want to mine them
  into a corpus so a new (year, make, model, service_type) query can be answered
  from his OWN past work instead of running the 5–7 min ALLDATA vision agent.

  This module scrapes COMPLETED ROs off the Tekmetric Job Board by reusing the
  already-logged-in Chrome session the worker drives (CDP :9222). It is
  STRICTLY READ-ONLY — it only navigates and reads innerText/links. It never
  clicks Save/Edit/Send/Void or mutates anything.

WHY DISCOVERY-FIRST:
  We don't have Tekmetric's Job Board DOM committed anywhere. Rather than guess
  selectors blind, run `--discover` once: it dumps the current URL, every nav
  link (text+href), every RO-looking link, a screenshot, and the page innerText.
  We read that, learn the real URL pattern + selectors, then `--scrape N` does
  structured extraction. Tekmetric is a normal React app (unlike ALLDATA's
  anti-scrape canvas), so document innerText is reliable; Gemini vision stays a
  last-resort fallback only.

USAGE (run on the VPS as the estimaro user):
  PYTHONPATH=. venv/bin/python -m scrapers.tekmetric_job_board --discover \
      --out /tmp/tekmetric_discovery.json
  PYTHONPATH=. venv/bin/python -m scrapers.tekmetric_job_board --scrape 20 \
      --out /tmp/historical_pilot.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from playwright.async_api import Page

from core.browser import ChromeDebugBrowser

TEKMETRIC_HOST = "tekmetric.com"
TEKMETRIC_URL = "https://shop.tekmetric.com/"

# German Sport Auto Repair = shop 1846 (confirmed via discovery; the bare
# dashboard is just a shop picker). The Repair Orders list lives here and
# carries the status filters (Completed / Posted) we mine.
SHOP_ID = 1846
RO_LIST_URL = f"https://shop.tekmetric.com/admin/shop/{SHOP_ID}/repair-orders"

# RO detail/list links on Tekmetric look like .../repair-order/12345 or
# .../repair-orders/12345 or carry an ?roId=. Kept broad on purpose — discovery
# confirms the real shape before --scrape relies on it.
_RO_LINK_RE = re.compile(r"repair[-_ ]?order", re.IGNORECASE)
_RO_NUM_RE = re.compile(r"(?:RO\s*#?|repair[-_ ]?order[s]?/)\s*(\d{3,7})", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Low-level page helpers (read-only)
# --------------------------------------------------------------------------- #
class SessionLostError(RuntimeError):
    """Raised when the Tekmetric tab is on the Sign-In page. We NEVER attempt
    an automated login (reCAPTCHA risk + account lock); the session must be
    re-seeded manually via noVNC."""


# CRITICAL — why this scraper never calls page.goto()/page.reload():
#   Tekmetric holds its auth purely in the running SPA's in-memory state. There
#   is NO auth cookie and NO token in localStorage (verified). Any full document
#   load (goto/reload) cold-boots the SPA, the auth check fails, and the tab
#   drops to "Sign in" — killing the manually-seeded session. So ALL navigation
#   here is client-side only: clicking in-app links and page.go_back() (which a
#   SPA handles via popstate WITHOUT a document reload, preserving memory).


async def _is_signed_out(page: Page) -> bool:
    if "redirect=" in page.url or "/forgot" in page.url:
        return True
    try:
        title = await page.title()
    except Exception:
        title = ""
    return "sign in" in (title or "").lower()


async def _wait_url(page: Page, must_contain: str, timeout_s: float = 20.0) -> bool:
    """Poll for a client-side route to land on `must_contain`. No reload."""
    deadline = timeout_s
    while deadline > 0:
        if await _is_signed_out(page):
            raise SessionLostError(f"signed out while waiting for '{must_contain}'")
        if must_contain in page.url:
            await asyncio.sleep(1.0)
            return True
        await asyncio.sleep(1.0)
        deadline -= 1.0
    return must_contain in page.url


async def _focus_tekmetric(browser: ChromeDebugBrowser, *, goto_ro_list: bool = True) -> Page:
    """Focus the EXISTING warm Tekmetric tab (never create/goto) and ensure we
    are logged in. Navigate to the RO list via an in-app click only.

    Raises SessionLostError if the tab is showing Sign-In — the caller must
    surface that to a human to re-seed the session via noVNC.
    """
    page = await browser.find_tab_by_url(TEKMETRIC_HOST)
    if page is None:
        raise SessionLostError(
            "no Tekmetric tab open — cannot scrape without a warm session. "
            "Open Tekmetric and log in via noVNC first."
        )
    await page.bring_to_front()
    await asyncio.sleep(1.5)
    if await _is_signed_out(page):
        raise SessionLostError(
            f"Tekmetric tab is on the Sign-In page ({page.url}). The seeded "
            "session is gone — re-login manually via noVNC, then retry."
        )
    if not goto_ro_list:
        return page

    # We need the RO LIST (board view). If we're not on it — or we're parked on
    # an RO DETAIL page (e.g. where a dropped run left the tab) — click an in-app
    # link to return to the list. A detail URL also contains "repair-orders", so
    # we explicitly detect the /repair-orders/<id> detail shape too.
    on_detail = re.search(r"/repair-orders/\d+", page.url) is not None
    if "repair-orders" not in page.url or on_detail:
        link = page.locator(
            "a[data-testid='app-menu-option-Job Board'], a[href$='/repair-orders']"
        ).first
        if await link.count() == 0:
            link = page.locator("a[href*='repair-orders']").first
        if await link.count() == 0:
            raise SessionLostError(
                f"logged in but no in-app Job-Board link on {page.url}; "
                "navigate to the RO list manually once, then retry."
            )
        await link.click()
        # Wait until we're on the LIST, not a detail page (id gone from URL).
        for _ in range(20):
            if "repair-orders" in page.url and not re.search(r"/repair-orders/\d+", page.url):
                break
            if await _is_signed_out(page):
                raise SessionLostError("signed out returning to Job Board")
            await asyncio.sleep(1.0)
    return page


# The Job Board "board" selector (top-right) groups ROs by lifecycle. "Paid"
# = completed + customer-paid = the ground-truth corpus we want. Verified live.
KNOWN_BOARDS = ["Active", "Saved for Later", "Accounts Receivable",
                "Paid", "Deleted", "Counter Sales"]


async def _dismiss_overlays(page: Page) -> None:
    """Close any open MUI menu/popover/backdrop so it can't intercept our next
    click. A stray open menu (e.g. the Recent-ROs dropdown) overlays the page
    with a transparent backdrop that swallows pointer events."""
    for _ in range(5):
        overlays = page.locator(".MuiModal-root, .MuiPopover-root, .MuiBackdrop-root")
        if await overlays.count() == 0:
            return
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.4)
    bd = page.locator(".MuiBackdrop-root").first
    if await bd.count():
        try:
            await bd.click(timeout=2000)  # MUI backdrops dismiss their popover
        except Exception:
            pass


async def _switch_board(page: Page, target: str) -> None:
    """Switch the Job Board to `target` via the in-app dropdown (client-side,
    no goto). The selector button shows the CURRENT board's name."""
    if target not in KNOWN_BOARDS:
        raise ValueError(f"unknown board '{target}' (expected one of {KNOWN_BOARDS})")
    await _dismiss_overlays(page)
    # The board selector is the only button carrying an ArrowDropDownIcon; its
    # text is the CURRENT board name. (get_by_role name-matching is unreliable
    # here — the icon perturbs the accessible name.)
    selector = page.locator('button:has(svg[data-testid="ArrowDropDownIcon"])').first
    if await selector.count() == 0:
        if await _is_signed_out(page):
            raise SessionLostError("signed out; board selector unavailable")
        raise RuntimeError(f"board selector not found on {page.url} — not on Job Board list")
    current = (await selector.inner_text()).strip()
    if current == target:
        logger.info(f"board already on '{target}'")
        return
    await selector.click()
    await asyncio.sleep(1.2)
    await page.locator(".MuiPopover-paper").get_by_text(target, exact=True).first.click()
    await asyncio.sleep(3.5)  # board reload (client-side)
    if await _is_signed_out(page):
        raise SessionLostError("signed out while switching board")
    logger.info(f"switched board '{current}' → '{target}' | url={page.url}")


async def _collect_links(page: Page) -> list[dict]:
    """Every anchor on the page as {text, href}. Used by discovery."""
    return await page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            text: (a.innerText || a.textContent || '').trim().slice(0, 80),
            href: a.href
        }))"""
    )


async def _collect_controls(page: Page) -> list[dict]:
    """Capture clickable controls (buttons, tabs, role=button, data-testid) so
    we can find the board/status switcher — these aren't <a> tags. Read-only."""
    return await page.evaluate(
        """() => {
            const sel = "button, [role=button], [role=tab], [data-testid], [aria-label]";
            const out = [];
            for (const el of document.querySelectorAll(sel)) {
                const txt = (el.innerText || el.textContent || '').trim().slice(0, 60);
                const aria = el.getAttribute('aria-label') || '';
                const tid = el.getAttribute('data-testid') || '';
                if (!txt && !aria && !tid) continue;
                out.push({tag: el.tagName.toLowerCase(), text: txt, aria, testid: tid});
            }
            return out.slice(0, 200);
        }"""
    )


async def _inner_text(page: Page, limit: int = 12000) -> str:
    try:
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"innerText failed: {e}")
        txt = ""
    return (txt or "")[:limit]


# --------------------------------------------------------------------------- #
# Phase A.1 — DISCOVERY
# --------------------------------------------------------------------------- #
async def discover(out_path: str, board: Optional[str] = None) -> dict:
    """Dump enough of the live Job Board to author real selectors from.

    Focuses the Tekmetric tab, optionally switches to `board`, screenshots it,
    lists nav + RO links and the page text. Only in-app clicks — no goto.
    """
    async with ChromeDebugBrowser() as browser:
        page = await _focus_tekmetric(browser)
        if board:
            await _switch_board(page, board)
        _, shot_path = await browser.screenshot(page, "tekmetric_discover")

        links = await _collect_links(page)
        ro_links = [l for l in links if _RO_LINK_RE.search(l["href"]) or _RO_LINK_RE.search(l["text"])]
        # Nav links = short-text links that aren't RO rows (Job Board, RO list, etc.)
        nav_links = [l for l in links if l["text"] and len(l["text"]) <= 40][:60]

        result = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "current_url": page.url,
            "title": await page.title(),
            "screenshot": shot_path,
            "total_links": len(links),
            "ro_links_sample": ro_links[:40],
            "nav_links_sample": nav_links,
            "controls_sample": await _collect_controls(page),
            "inner_text_head": await _inner_text(page, 8000),
        }

    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        f"Discovery saved → {out_path} | url={result['current_url']} | "
        f"links={result['total_links']} ro_links={len(result['ro_links_sample'])}"
    )
    return result


# --------------------------------------------------------------------------- #
# Phase A.2 — SCRAPE (selectors refined after discovery)
# --------------------------------------------------------------------------- #
async def _find_completed_ro_urls(page: Page, limit: int) -> list[str]:
    """Collect detail URLs for completed ROs from the current Job Board view.

    Heuristic for the pilot: any anchor whose href matches the RO pattern.
    After discovery we tighten this to the Completed column/tab selector.
    """
    links = await _collect_links(page)
    urls: list[str] = []
    seen: set[str] = set()
    for l in links:
        href = l["href"]
        if _RO_LINK_RE.search(href) and _RO_NUM_RE.search(href):
            if href not in seen:
                seen.add(href)
                urls.append(href)
        if len(urls) >= limit:
            break
    return urls


def _money(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def parse_ro_detail(text: str) -> dict:
    """Parse an RO detail page's flat innerText into corpus header fields.

    Tekmetric renders the whole RO (header, vehicle, customer, per-job line
    items, totals) as plain DOM text — no canvas, no vision needed. We anchor
    on the page's own labels (each label sits on its own line, value on the
    next). The per-job line-item parse is deliberately left to Phase B (offline,
    against saved samples); here we keep the high-confidence header/breakdown
    fields and ALWAYS retain raw_text so nothing is lost.
    """
    out: dict[str, Any] = {}
    m = re.search(r"RO #(\d+):\s*(.+)", text)
    if m:
        out["ro_number"] = m.group(1)
        out["title"] = m.group(2).strip()
        ym = re.search(r"(.+?)'s\s+((?:19|20)\d{2})\s+(.+)", m.group(2))
        if ym:
            out["customer_name"] = ym.group(1).strip()
            out["year"] = int(ym.group(2))
            # Paid/posted RO headings append a status badge, e.g. "... (PAID)".
            mm = re.sub(r"\s*\((?:PAID|POSTED|COMPLETED|INVOICED?)\)\s*$", "",
                        ym.group(3).strip(), flags=re.IGNORECASE)
            out["make_model"] = mm.strip()

    v = re.search(r"\bVIN\b\s*\n\s*([A-HJ-NPR-Z0-9]{17})", text)
    if v:
        out["vin"] = v.group(1)
    for label, key in (("Body Type", "body_type"), ("Transmission", "transmission"),
                       ("Drivetrain", "drivetrain")):
        mm = re.search(rf"\n{label}\s*\n\s*(.+)", text)
        if mm:
            out[key] = mm.group(1).strip()
    od = re.search(r"In:\s*([\d,]+)", text)
    if od:
        out["odometer_in"] = od.group(1).replace(",", "")
    oo = re.search(r"Out:\s*([\d,]+)", text)
    if oo:
        out["odometer_out"] = oo.group(1).replace(",", "")
    lr = re.search(r"Labor Rate\s*\n\s*\$([\d,]+\.\d{2})", text)
    if lr:
        out["labor_rate"] = _money(lr.group(1))
    ph = re.search(r"\nPhone\s*\n\s*(\(?\d[\d()\s\-]{6,})", text)
    if ph:
        out["phone"] = ph.group(1).strip()

    # Grand totals live in the trailing "BUILD ESTIMATE" summary block — anchor
    # there so per-job "Subtotal/Total" lines above don't get picked up.
    be = text.split("BUILD ESTIMATE")[-1]
    for label, key in (("Labor", "labor_total"), ("Parts", "parts_total"),
                       ("Sublet", "sublet"), ("Fees", "fees"),
                       ("Discounts", "discounts"), ("Subtotal", "subtotal"),
                       ("Taxes", "taxes"), ("Total", "total")):
        mm = re.search(rf"\n{label}\s*\n\$([\d,]+\.\d{{2}})", be)
        if mm:
            out[key] = _money(mm.group(1))
    return out


async def _extract_jobs(page: Page) -> list[dict]:
    """Capture each job's complete line-item block via its job-table testid.

    Returns [{job_id, text}] where text holds the full labor + parts rows for
    that job. The precise field split happens offline in Phase B."""
    return await page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-testid^="job-table-"]'))
            .map(t => ({
                job_id: t.getAttribute('data-testid').replace('job-table-', ''),
                text: (t.innerText || '').trim()
            }))"""
    )


async def _paid_page_rows(page: Page) -> list[dict]:
    """Read the Paid/POSTED list table's current page into row summaries.

    Columns: Date Posted, RO#, Customer/Vehicle, Unit#, Odometer Out, Phone,
    Total. Rows are plain <tr> (no href) — clicking navigates to the detail."""
    cells_rows = await page.evaluate(
        """() => Array.from(document.querySelectorAll('tr'))
            .map(r => Array.from(r.querySelectorAll('td')).map(c => (c.innerText||'').trim()))
            .filter(cells => cells.length >= 6)"""
    )
    rows: list[dict] = []
    for c in cells_rows:
        ro = re.search(r"\b(\d{4,7})\b", c[1]) if len(c) > 1 else None
        cust_veh = c[2] if len(c) > 2 else ""
        total = _money(re.search(r"\$([\d,]+\.\d{2})", " ".join(c)).group(1)
                       if re.search(r"\$([\d,]+\.\d{2})", " ".join(c)) else None)
        if not ro:
            continue
        ym = re.search(r"((?:19|20)\d{2})\s+(.+)", cust_veh.replace("\n", " "))
        rows.append({
            "ro_number": ro.group(1),
            "date_posted": c[0].strip() if c else None,
            "customer_vehicle": cust_veh.replace("\n", " ").strip(),
            "year": int(ym.group(1)) if ym else None,
            "make_model": ym.group(2).strip() if ym else None,
            "list_total": total,
        })
    return rows


async def _paid_first_ro(page: Page) -> Optional[str]:
    rows = await _paid_page_rows(page)
    return rows[0]["ro_number"] if rows else None


async def _paid_footer(page: Page) -> Optional[tuple[int, int, int]]:
    """Read the list footer 'start - end of total' (e.g. 201-300 of 30396).
    This is the AUTHORITATIVE end-of-list signal — far more reliable than the
    next-button's disabled state, which flickers during slow 100-row reloads."""
    txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
    m = re.search(r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*of\s*(\d[\d,]*)", txt or "")
    if not m:
        return None
    f = lambda s: int(s.replace(",", ""))
    return f(m.group(1)), f(m.group(2)), f(m.group(3))


async def _goto_next_paid_page(page: Page) -> bool:
    """Advance the Paid list by one page, robust to transient stalls.

    Earlier runs stopped at DIFFERENT offsets (~4970, then ~6800) — proof the
    stops were transient (the next arrow flickers disabled / the 100-row page
    reloads slower than our wait), NOT a hard cap. So we trust the FOOTER: only
    declare 'done' when end >= total; otherwise click and retry until the first
    row actually changes."""
    foot = await _paid_footer(page)
    if foot and foot[1] >= foot[2]:
        return False  # genuinely at the last row of the list
    before = await _paid_first_ro(page)
    btn = page.locator('button:has(svg[data-testid="KeyboardArrowRightIcon"])').first
    for attempt in range(5):
        if await btn.count() and not await btn.is_disabled():
            try:
                await btn.click()
            except Exception:
                pass
        else:
            await asyncio.sleep(2.0)  # button mid-render; let it settle, retry
        for _ in range(15):
            await asyncio.sleep(1.0)
            after = await _paid_first_ro(page)
            if after and after != before:
                return True
            if await _is_signed_out(page):
                raise SessionLostError("signed out during pagination")
        logger.warning(f"next-page no advance (attempt {attempt + 1}/5); "
                       f"footer={await _paid_footer(page)}")
    logger.error(f"pagination stuck before end; footer={await _paid_footer(page)}")
    return False


def _load_seen(jsonl_path: str) -> set[str]:
    """Rebuild the set of already-scraped RO numbers from an existing JSONL so
    a resumed run skips them. Tolerant of a half-written final line."""
    seen: set[str] = set()
    p = Path(jsonl_path)
    if not p.exists():
        return seen
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ro = json.loads(line).get("ro_number")
            if ro:
                seen.add(str(ro))
        except json.JSONDecodeError:
            continue  # truncated last line from a hard kill — ignore
    return seen


async def _scrape_one_paid_ro(page: Page, row: dict) -> dict:
    """Open one Paid RO via in-app row click, capture full detail, return to the
    list via go_back. Raises SessionLostError on logout; other errors bubble to
    the caller which records them and moves on."""
    ro = row["ro_number"]
    await page.locator("tr", has_text=ro).first.click(timeout=8000)
    for _ in range(20):
        if "/repair-orders/" in page.url and "board=" not in page.url:
            break
        if await _is_signed_out(page):
            raise SessionLostError("signed out opening paid RO")
        await asyncio.sleep(1.0)
    await asyncio.sleep(2.0)
    internal_id = page.url.rstrip("/").split("/")[-1].split("?")[0]
    text = await _inner_text(page, 24000)
    jobs = await _extract_jobs(page)
    detail = parse_ro_detail(text)
    rec = {"source_url": page.url, "internal_id": internal_id,
           "date_posted": row.get("date_posted"), "list_total": row.get("list_total"),
           "customer_vehicle": row.get("customer_vehicle"),
           **detail, "jobs": jobs, "raw_text": text}
    await page.go_back()
    for _ in range(15):
        if "board=POSTED" in page.url:
            break
        if await _is_signed_out(page):
            raise SessionLostError("signed out after paid go_back")
        await asyncio.sleep(1.0)
    await asyncio.sleep(1.0)
    return rec


async def _set_paid_page_size(page: Page, n: int = 100) -> bool:
    """Set the Paid list's rows-per-page via its native <select name="size">
    (Playwright drives the real element even though MUI styles it custom)."""
    try:
        await page.select_option('select[name="size"]', str(n))
        await asyncio.sleep(3.0)
        logger.info(f"paid rows-per-page set to {n}")
        return True
    except Exception as e:
        logger.warning(f"set page size failed: {e}")
        return False


async def scrape_paid(limit: int, out_path: str, *, skip_zero: bool = True,
                      page_size: int = 100, resume: bool = True) -> dict:
    """Scrape the Paid/POSTED board (the ~30k-RO ground-truth corpus).

    Writes one JSON object per RO, incrementally, to `<out_path>` as JSONL so a
    long run is crash-safe and resumable. On resume it rebuilds the seen-set
    from the existing file and skips done ROs (the Paid list is Date-Posted-desc,
    so newly-posted ROs shift positions — we dedupe by RO number, not page).

    On session loss it flushes and exits cleanly (SystemExit-style via re-raise)
    so progress is never lost; re-login via noVNC and re-run to continue.

    `limit` caps newly-scraped ROs this run (use a huge number for "all").
    """
    jsonl = Path(out_path)
    seen = _load_seen(out_path) if resume else set()
    done_before = len(seen)
    new_count = 0
    errors = 0
    logger.info(f"Paid scrape → {out_path} | resuming with {done_before} already done, "
                f"limit={limit} new this run")

    fh = jsonl.open("a", encoding="utf-8")
    try:
        async with ChromeDebugBrowser() as browser:
            page = await _focus_tekmetric(browser)
            # Normalize to Paid page 0 regardless of where a prior run left the
            # tab: bounce through Active so board=POSTED reloads at page=0 (the
            # list is Date-Posted-desc; we dedupe by RO number, so we must always
            # start from the top to avoid skipping unseen ROs on earlier pages).
            await _switch_board(page, "Active")
            await _switch_board(page, "Paid")
            # 100 rows/page: fewer page clicks AND it pushes past the list's
            # deep-pagination cap if that cap is page-count- rather than
            # row-offset-based (500 pages × 100 = 50k > 30,396).
            if page_size and page_size != 10:
                await _set_paid_page_size(page, page_size)

            while new_count < limit:
                rows = await _paid_page_rows(page)
                if not rows:
                    # A transient empty render must NOT silently end the scrape
                    # (it cost us ~17k rows once). Retry; only stop if the page
                    # is truly empty AND the footer says we're at the last row.
                    for _ in range(6):
                        await asyncio.sleep(2.0)
                        rows = await _paid_page_rows(page)
                        if rows:
                            break
                    if not rows:
                        foot = await _paid_footer(page)
                        logger.warning(f"no rows after retries; footer={foot}")
                        if foot and foot[1] < foot[2]:
                            # not at the end — try to nudge to the next page once
                            if await _goto_next_paid_page(page):
                                continue
                        break
                # NOTE: no per-page 'first RO unchanged' stuck-check here — it
                # false-fired on transient re-renders and silently truncated the
                # run. Advancement is owned solely by _goto_next_paid_page(),
                # which retries and uses the footer (end >= total) as the
                # authoritative end-of-list signal.

                for row in rows:
                    if new_count >= limit:
                        break
                    ro = row["ro_number"]
                    if ro in seen:
                        continue
                    seen.add(ro)
                    if skip_zero and (row["list_total"] or 0) <= 0:
                        continue
                    try:
                        rec = await _scrape_one_paid_ro(page, row)
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fh.flush()
                        new_count += 1
                        if new_count % 20 == 0 or new_count <= 5:
                            logger.info(
                                f"[+{new_count} | {done_before + new_count} total] "
                                f"RO#{rec.get('ro_number','?')} {rec.get('year','?')} "
                                f"{rec.get('make_model','?')} ${rec.get('total','?')} "
                                f"jobs={len(rec.get('jobs', []))}")
                    except SessionLostError:
                        raise
                    except Exception as e:
                        errors += 1
                        logger.error(f"paid RO#{ro} failed: {type(e).__name__}: {e}")
                        fh.write(json.dumps({"ro_number": ro,
                                             "error": f"{type(e).__name__}: {e}"}) + "\n")
                        fh.flush()
                if new_count >= limit:
                    break
                if not await _goto_next_paid_page(page):
                    logger.info("reached last paid page")
                    break
    except SessionLostError as e:
        logger.error(f"SESSION LOST after +{new_count} new ({done_before + new_count} "
                     f"total) — re-login via noVNC and re-run to resume: {e}")
        raise
    finally:
        fh.close()

    total = done_before + new_count
    logger.info(f"Paid scrape done → {out_path} | +{new_count} new, {errors} errors, "
                f"{total} total in file")
    return {"new": new_count, "errors": errors, "total": total, "out": out_path}


async def scrape(limit: int, out_path: str, board: Optional[str] = None) -> dict:
    """Visit up to `limit` RO detail pages and dump a structured-ish record each.

    Read-only. Output is deliberately raw (includes per-RO innerText) so the
    shape can be hand-validated before Phase B normalizes it into the corpus DB.
    """
    records: list[dict] = []
    async with ChromeDebugBrowser() as browser:
        page = await _focus_tekmetric(browser)
        if board:
            await _switch_board(page, board)
        ro_urls = await _find_completed_ro_urls(page, limit)
        logger.info(f"Found {len(ro_urls)} candidate RO urls (limit={limit})")

        for i, url in enumerate(ro_urls, 1):
            try:
                # Client-side nav ONLY: click the in-app anchor, never goto.
                # Match on the RO id via ends-with — the anchor's href ATTRIBUTE
                # is relative ("/admin/.../<id>"), so an exact absolute-URL
                # selector never matches (that bit us with 30s timeouts).
                ro_id = url.rstrip("/").split("/")[-1]
                await page.locator(f'a[href$="/repair-orders/{ro_id}"]').first.click(timeout=8000)
                await _wait_url(page, f"/repair-orders/{ro_id}")
                await asyncio.sleep(2.0)
                if await _is_signed_out(page):
                    raise SessionLostError("signed out mid-scrape")
                text = await _inner_text(page, 24000)
                jobs = await _extract_jobs(page)
                rec = {"source_url": page.url, **parse_ro_detail(text),
                       "jobs": jobs, "raw_text": text}
                records.append(rec)
                logger.info(
                    f"[{i}/{len(ro_urls)}] RO#{rec.get('ro_number','?')} "
                    f"{rec.get('year','?')} {rec.get('make_model','?')} "
                    f"total=${rec.get('total','?')} jobs={len(jobs)} vin={rec.get('vin','?')}"
                )
                # Return to the list via SPA history (popstate, no reload).
                # Wait until we've actually LEFT this RO's detail (its id is
                # gone from the URL) — "repair-orders" alone also matches detail.
                await page.go_back()
                for _ in range(15):
                    if await _is_signed_out(page):
                        raise SessionLostError("signed out after go_back")
                    if f"/repair-orders/{ro_id}" not in page.url:
                        break
                    await asyncio.sleep(1.0)
                await asyncio.sleep(1.0)
            except SessionLostError:
                raise  # fatal — surface to human, don't keep hammering
            except Exception as e:
                logger.error(f"[{i}/{len(ro_urls)}] scrape failed {url}: {type(e).__name__}: {e}")
                records.append({"source_url": url, "error": f"{type(e).__name__}: {e}"})

    result = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(records),
        "records": records,
    }
    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Scrape saved → {out_path} | {len(records)} records")
    return result


# --------------------------------------------------------------------------- #
async def check() -> dict:
    """Safe login-state probe: focus the warm tab, report URL/title only.
    Does NOT navigate or click — use this after a noVNC re-login to confirm
    the session is healthy before running --discover/--scrape."""
    async with ChromeDebugBrowser() as browser:
        page = await browser.find_tab_by_url(TEKMETRIC_HOST)
        if page is None:
            return {"signed_in": False, "reason": "no Tekmetric tab open"}
        await page.bring_to_front()
        await asyncio.sleep(1.0)
        signed_out = await _is_signed_out(page)
        info = {"signed_in": not signed_out, "url": page.url, "title": await page.title()}
        logger.info(f"check: {info}")
        return info


def main() -> None:
    ap = argparse.ArgumentParser(description="Tekmetric Job Board scraper (Phase A)")
    ap.add_argument("--check", action="store_true", help="probe login state only (no nav)")
    ap.add_argument("--discover", action="store_true", help="dump live Job Board structure")
    ap.add_argument("--scrape", type=int, metavar="N", help="scrape up to N completed ROs")
    ap.add_argument("--board", choices=KNOWN_BOARDS, metavar="BOARD",
                    help=f"Job Board to switch to before scraping (one of {KNOWN_BOARDS})")
    ap.add_argument("--out", help="output path (JSON for non-Paid; JSONL for --board Paid)")
    ap.add_argument("--page-size", type=int, default=100,
                    help="Paid list rows-per-page (default 100)")
    ap.add_argument("--no-resume", action="store_true",
                    help="Paid: do NOT resume from an existing output file")
    args = ap.parse_args()

    try:
        if args.check:
            print(json.dumps(asyncio.run(check()), indent=2))
        elif args.discover:
            if not args.out:
                ap.error("--discover requires --out")
            asyncio.run(discover(args.out, board=args.board))
        elif args.scrape:
            if not args.out:
                ap.error("--scrape requires --out")
            if args.board == "Paid":
                # Paid/POSTED is a paginated LIST (rows, not anchors) — use the
                # resumable JSONL row-click path that yields the corpus.
                print(json.dumps(asyncio.run(scrape_paid(
                    args.scrape, args.out, page_size=args.page_size,
                    resume=not args.no_resume)), indent=2))
            else:
                asyncio.run(scrape(args.scrape, args.out, board=args.board))
        else:
            ap.error("pass --check, --discover, or --scrape N")
    except SessionLostError as e:
        logger.error(f"SESSION LOST — manual noVNC re-login required: {e}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
