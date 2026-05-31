"""Auto-login / session watchdog for the vendor portals.

Design goals: scalability + stability.
  * Deterministic Playwright login (NOT vision) so it is fast and reliable and
    the password is NEVER sent to the LLM.
  * Credentials are read from settings (.env) only — never hard-coded, never
    logged. We log usernames and status, never passwords.
  * `ensure_logged_in(portal)` is called right before a portal agent runs, so a
    session that has dropped is transparently restored on demand. A standalone
    `relogin_all()` is also exposed for a periodic keep-alive / cron.

Each portal entry only needs: where to land, how to tell we're logged out, and
which credential keys to use. Generic selectors handle the common login form;
per-portal `extra` handles oddities (e.g. PartsLink24's Company ID).
"""
import asyncio
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from config import settings
from core.browser import ChromeDebugBrowser


# portal_key -> config
PORTALS: dict[str, dict] = {
    "alldata": {
        "url": "https://my.alldata.com/migrate/#/home",
        "match": "alldata.com",
        "user": "ALLDATA_USERNAME", "passwd": "ALLDATA_PASSWORD",
    },
    "partslink24": {
        "url": "https://www.partslink24.com/partslink24/user/login.do",
        "match": "partslink24.com",
        "user": "PARTSLINK24_USERNAME", "passwd": "PARTSLINK24_PASSWORD",
        # PL24's login form has THREE fields whose names all contain "login":
        #   accountLogin       -> Company ID
        #   userLogin          -> Username
        #   loginBean.password -> Password
        # The generic _USER_SEL matches all three on `name*='login' i`, so the
        # legacy auto-pick was scrambling Company ID with Username. Pin each
        # role to its exact name. The visible submit is `#hidden-login` with
        # class auto-submit and display:none, so we click it via JS rather
        # than relying on :visible.
        "fields": {
            "user":   "input[name='userLogin']",
            "passwd": "input[name='loginBean.password']",
            "extras": [{"selector": "input[name='accountLogin']",
                         "value_key": "PARTSLINK24_COMPANY_ID"}],
        },
        # Submit button is hidden; click it via JS rather than rely on :visible.
        "submit_js": "() => { const b = document.querySelector('#hidden-login'); if (b) b.click(); }",
        # After successful login PL24 redirects away from /user/login.do to the
        # brand menu. Use URL as the success signal, not just \"password field gone\".
        "logged_in_url_excludes": "/user/login.do",
    },
    "ssf": {
        "url": "https://shop.ssfautoparts.com/",
        "match": "ssfautoparts.com",
        "user": "SSF_USERNAME", "passwd": "SSF_PASSWORD",
    },
    "worldpac": {
        "url": "https://speeddial.worldpac.com/#/login",
        "match": "worldpac.com",
        "user": "WORLDPAC_USERNAME", "passwd": "WORLDPAC_PASSWORD",
    },
    "tekmetric": {
        # Hit the admin shell so the login redirect fires when the session is
        # only "shallow"-valid (cookie present but the per-shop scope has
        # expired). The dashboard URL is what every real action lives behind.
        "url": "https://shop.tekmetric.com/admin/dashboard",
        "match": "tekmetric.com",
        "user": "TEKMETRIC_USERNAME", "passwd": "TEKMETRIC_PASSWORD",
    },
}

# Generic selectors for a standard login form.
_PW_SEL = "input[type=password]"
_USER_SEL = (
    "input[type=email]:visible, input[name*='user' i]:visible, "
    "input[id*='user' i]:visible, input[name*='login' i]:visible, "
    "input[type=text]:visible"
)
_SUBMIT_SEL = (
    "input[type=submit]:visible, button[type=submit]:visible, "
    "button:has-text('Log In'):visible, button:has-text('Login'):visible, "
    "button:has-text('Sign In'):visible, button:has-text('Sign in'):visible"
)


async def _password_field(page: Page):
    """Return a visible password input locator if a login form is present."""
    loc = page.locator(f"{_PW_SEL}:visible")
    try:
        if await loc.count() > 0:
            return loc.first
    except Exception:
        pass
    return None


async def is_logged_out(page: Page) -> bool:
    """Heuristic: a visible password field means we're on a login screen."""
    return (await _password_field(page)) is not None


async def _do_login(page: Page, cfg: dict) -> bool:
    user = getattr(settings, cfg["user"], "") or ""
    pw = getattr(settings, cfg["passwd"], "") or ""
    if not user or not pw:
        logger.error(f"[auth] missing credentials for {cfg['user']} / {cfg['passwd']} "
                     f"— add them to .env on the VPS")
        return False

    pw_field = await _password_field(page)
    if pw_field is None:
        return True  # already logged in

    fields = cfg.get("fields") or {}

    # Username — prefer explicit per-portal selector, else fall back to generic.
    try:
        user_sel = fields.get("user") or _USER_SEL
        ufield = page.locator(user_sel).first
        await ufield.fill("")
        await ufield.fill(user)
    except Exception as e:
        logger.warning(f"[auth] username fill issue: {e}")

    # Extras — per-portal explicit (PL24 Company ID), then legacy hint-based.
    for extra in fields.get("extras", []):
        val = getattr(settings, extra["value_key"], "") or ""
        if not val:
            continue
        try:
            f = page.locator(extra["selector"]).first
            if await f.count() > 0:
                await f.fill("")
                await f.fill(val)
        except Exception as e:
            logger.warning(f"[auth] extra fill ({extra['value_key']}) issue: {e}")
    for extra in cfg.get("extra", []):  # legacy hint-based path (other portals)
        val = getattr(settings, extra["value_key"], "") or ""
        if not val:
            continue
        for hint in extra["hints"]:
            try:
                f = page.locator(
                    f"input[name*='{hint}' i]:visible, input[id*='{hint}' i]:visible,"
                    f"input[placeholder*='{hint}' i]:visible"
                ).first
                if await f.count() > 0:
                    await f.fill(val)
                    break
            except Exception:
                continue

    # Password — explicit selector if provided (PL24 has multiple pw-ish fields
    # over its lifetime; pinning the name avoids the wrong one).
    try:
        if fields.get("passwd"):
            await page.locator(fields["passwd"]).first.fill(pw)
        else:
            await pw_field.fill(pw)
    except Exception as e:
        logger.error(f"[auth] password fill failed: {e}")
        return False

    # Submit — per-portal JS first (handles hidden submit buttons), then the
    # generic visible-button path, then Enter on the password field.
    submitted = False
    if cfg.get("submit_js"):
        try:
            await page.evaluate(cfg["submit_js"])
            submitted = True
        except Exception as e:
            logger.warning(f"[auth] submit_js failed: {e}")
    if not submitted:
        try:
            submit = page.locator(_SUBMIT_SEL).first
            if await submit.count() > 0:
                await submit.click()
                submitted = True
        except Exception as e:
            logger.warning(f"[auth] submit click issue: {e}")
    if not submitted:
        try:
            await pw_field.press("Enter")
        except Exception:
            pass

    # Success signal: prefer URL-based marker when the portal redirects on
    # success (PL24), else fall back to the password field disappearing.
    url_marker = cfg.get("logged_in_url_excludes")
    for _ in range(12):
        await asyncio.sleep(1.5)
        if url_marker and url_marker not in page.url:
            return True
        if not await is_logged_out(page):
            return True
    # Final state — log the post-submit URL so an operator can see if the
    # form was rejected (still on login.do) vs site error (somewhere else).
    logger.warning(f"[auth] post-submit URL: {page.url}")
    return False


async def ensure_logged_in(portal_key: str) -> dict:
    """Open the portal; if a login form is showing, log in. Returns a status dict.
    Safe to call before every portal agent run."""
    cfg = PORTALS.get(portal_key)
    if not cfg:
        return {"portal": portal_key, "ok": False, "error": "unknown portal"}

    try:
        async with ChromeDebugBrowser() as browser:
            page = await browser.open_or_focus(cfg["url"], url_match=cfg["match"])
            await asyncio.sleep(2)
            if not await is_logged_out(page):
                return {"portal": portal_key, "ok": True, "action": "already_logged_in"}

            logger.info(f"[auth] {portal_key}: session dropped — re-logging in as "
                        f"{getattr(settings, cfg['user'], '') or '(no user set)'}")
            ok = await _do_login(page, cfg)
            return {"portal": portal_key, "ok": ok,
                    "action": "relogin" if ok else "relogin_failed"}
    except Exception as e:
        logger.error(f"[auth] {portal_key} ensure_logged_in error: {e}")
        return {"portal": portal_key, "ok": False, "error": str(e)[:160]}


async def restore_session_on_page(page: Page, portal_key: str) -> bool:
    """Re-login on an EXISTING page (no new browser context).

    Use this from inside a running vision-agent when mid-flight session
    expiry is detected — calling `ensure_logged_in` would open a separate
    ChromeDebugBrowser context which fights the agent for tabs and adds
    latency. With this helper we drive the login form on the same page the
    agent is already holding, then the agent simply navigates back to its
    portal_url and continues from there.

    Returns True when, after the attempt, the page is no longer showing a
    login form (or, for portals that use a URL marker, the URL no longer
    matches the login route). Returns False if credentials are missing,
    the portal_key is unknown, or the form remains visible after submit.
    """
    cfg = PORTALS.get(portal_key)
    if not cfg:
        logger.warning(f"[auth] restore_session_on_page: unknown portal {portal_key!r}")
        return False
    try:
        return await _do_login(page, cfg)
    except Exception as e:
        logger.error(f"[auth] restore_session_on_page {portal_key} error: {e}")
        return False


async def relogin_all() -> list[dict]:
    """Check + restore every portal session. Use from a periodic keep-alive."""
    results = []
    for key in PORTALS:
        results.append(await ensure_logged_in(key))
    return results


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target == "all":
        out = asyncio.run(relogin_all())
    else:
        out = [asyncio.run(ensure_logged_in(target))]
    for r in out:
        print(r)
