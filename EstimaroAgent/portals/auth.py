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
        # PartsLink24 also asks for a Company/Login ID on the login screen.
        "extra": [{"hints": ["company", "login id", "customer", "userlogin"],
                    "value_key": "PARTSLINK24_COMPANY_ID"}],
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

    # Username
    try:
        ufield = page.locator(_USER_SEL).first
        await ufield.fill("")
        await ufield.fill(user)
    except Exception as e:
        logger.warning(f"[auth] username fill issue: {e}")

    # Extra fields (e.g. PartsLink24 Company ID) — best effort, before password.
    for extra in cfg.get("extra", []):
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

    # Password (filled locally; never logged, never sent to the LLM)
    try:
        await pw_field.fill(pw)
    except Exception as e:
        logger.error(f"[auth] password fill failed: {e}")
        return False

    # Submit
    try:
        submit = page.locator(_SUBMIT_SEL).first
        if await submit.count() > 0:
            await submit.click()
        else:
            await pw_field.press("Enter")
    except Exception as e:
        logger.warning(f"[auth] submit issue: {e}; trying Enter")
        try:
            await pw_field.press("Enter")
        except Exception:
            pass

    # Wait for navigation / form to disappear
    for _ in range(10):
        await asyncio.sleep(1.5)
        if not await is_logged_out(page):
            return True
    return not await is_logged_out(page)


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
