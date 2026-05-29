"""DOM annotation helper: inject numbered overlays on every interactive element,
take a screenshot, and return both the element list and the annotated image.

Gemini then picks elements by ID instead of fabricating CSS selectors.
"""
from typing import Optional
from playwright.async_api import Page


_INJECT_JS = r"""
(() => {
  // Remove any prior overlay
  const prior = document.getElementById('__agent_overlay__');
  if (prior) prior.remove();

  // Clear prior data-agent-id
  document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));

  const SEL = [
    'a[href]',
    'button',
    '[role="button"]',
    '[role="tab"]',
    '[role="option"]',
    '[role="menuitem"]',
    '[role="menuitemradio"]',
    '[role="menuitemcheckbox"]',
    '[role="combobox"]',
    '[role="listbox"]',
    '[role="row"]',
    '[role="cell"]',
    '[role="gridcell"]',
    '[role="treeitem"]',
    '[role="link"]',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    'li',
    'tr',
    '[onclick]',
    '[tabindex]:not([tabindex="-1"])',
    'label',
    '[class*="tile"]',
    '[class*="card"]',
    '[class*="result"]',
    '[class*="row"]',
    '[class*="item"]',
    '[class*="option"]',
    '[class*="select"]'
  ].join(', ');

  const seen = new WeakSet();
  const items = [];

  function visible(el) {
    if (!el || seen.has(el)) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    if (r.bottom < 0 || r.top > window.innerHeight) return false;
    if (r.right < 0 || r.left > window.innerWidth) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.1) return false;
    return true;
  }

  function txt(el) {
    let t = (el.innerText || el.value || el.placeholder ||
             el.getAttribute('aria-label') || el.getAttribute('title') ||
             el.getAttribute('alt') || '').trim();
    return t.replace(/\s+/g, ' ').slice(0, 100);
  }

  Array.from(document.querySelectorAll(SEL)).forEach(el => {
    if (!visible(el)) return;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const id = items.length;
    el.setAttribute('data-agent-id', String(id));
    items.push({
      id,
      tag: el.tagName.toLowerCase(),
      type: (el.type || '').toString(),
      text: txt(el),
      name: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      role: el.getAttribute('role') || '',
      href: el.tagName === 'A' ? (el.getAttribute('href') || '') : '',
      bounds: {
        x: Math.round(r.left), y: Math.round(r.top),
        w: Math.round(r.width), h: Math.round(r.height)
      }
    });
  });

  // Build overlay
  const overlay = document.createElement('div');
  overlay.id = '__agent_overlay__';
  Object.assign(overlay.style, {
    position: 'fixed', top: '0', left: '0',
    width: '100%', height: '100%',
    pointerEvents: 'none', zIndex: '2147483647'
  });

  items.forEach(it => {
    const box = document.createElement('div');
    Object.assign(box.style, {
      position: 'absolute',
      left: it.bounds.x + 'px',
      top: it.bounds.y + 'px',
      width: it.bounds.w + 'px',
      height: it.bounds.h + 'px',
      border: '2px solid rgba(255, 30, 30, 0.85)',
      boxSizing: 'border-box',
      borderRadius: '2px'
    });
    const tag = document.createElement('div');
    tag.textContent = it.id;
    Object.assign(tag.style, {
      position: 'absolute',
      left: Math.max(0, it.bounds.x) + 'px',
      top: Math.max(0, it.bounds.y - 14) + 'px',
      background: 'rgba(220, 0, 0, 0.95)',
      color: 'white',
      font: 'bold 11px monospace',
      padding: '0 4px',
      lineHeight: '14px',
      borderRadius: '2px'
    });
    overlay.appendChild(box);
    overlay.appendChild(tag);
  });
  document.body.appendChild(overlay);
  return items;
})()
"""

_CLEAR_JS = r"""
(() => {
  const o = document.getElementById('__agent_overlay__');
  if (o) o.remove();
})()
"""


async def annotate(page: Page) -> list[dict]:
    """Inject overlay + data-agent-id and return the element list."""
    items = await page.evaluate(_INJECT_JS)
    return items or []


async def clear(page: Page):
    """Remove the overlay (call before screenshotting for end-user reports)."""
    try:
        await page.evaluate(_CLEAR_JS)
    except Exception:
        pass


async def annotated_screenshot(page: Page, full_page: bool = False) -> tuple[list[dict], bytes]:
    """One-shot: annotate, screenshot, return (elements, png_bytes).
    The overlay stays on the page after this call so subsequent actions
    can target elements by data-agent-id. Call `clear(page)` to remove it.
    """
    items = await annotate(page)
    shot = await page.screenshot(full_page=full_page)
    return items, shot


def format_elements_for_prompt(items: list[dict], max_items: int = 60) -> str:
    """Compact textual representation for the LLM prompt."""
    lines = []
    for it in items[:max_items]:
        parts = [f"#{it['id']}", f"<{it['tag']}"]
        if it.get('type'):
            parts.append(f" type={it['type']}")
        if it.get('role'):
            parts.append(f" role={it['role']}")
        if it.get('name'):
            parts.append(f" name={it['name']}")
        parts.append(">")
        text = it.get('text', '')
        if not text and it.get('placeholder'):
            text = f"[placeholder: {it['placeholder']}]"
        if not text and it.get('href'):
            text = f"[link: {it['href'][:50]}]"
        parts.append(f"  {text}")
        lines.append("".join(parts))
    if len(items) > max_items:
        lines.append(f"... and {len(items) - max_items} more elements (use scroll or be more specific)")
    return "\n".join(lines)
