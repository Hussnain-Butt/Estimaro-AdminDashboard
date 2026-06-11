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
        # SpeedDIAL 2.0's "password" field is <input type="text" name="password">
        # (it has a show/hide eye, so it's NOT type=password). The generic
        # password-field heuristic therefore finds NO form and wrongly reports
        # "already logged in", so auto-login never runs. Authoritative signals:
        #   * logged out  -> the SPA route is "#/login"
        #   * logged in   -> URL no longer contains "/login"
        # and pin the username/password fields by name.
        "logged_out_url_marker": "/login",
        "logged_in_url_excludes": "/login",
        "fields": {
            "user":   "input[name='username']",
            "passwd": "input[name='password']",
        },
    },
    "tekmetric": {
        # Hit the admin shell so the login redirect fires when the session is
        # only "shallow"-valid (cookie present but the per-shop scope has
        # expired). The dashboard URL is what every real action lives behind.
        "url": "https://shop.tekmetric.com/admin/dashboard",
        "match": "tekmetric.com",
        "user": "TEKMETRIC_USERNAME", "passwd": "TEKMETRIC_PASSWORD",
        # When the session is dead Tekmetric DOES NOT show the login form on
        # the dashboard URL — it 302s to the marketing root with a
        # `?redirect=/admin/...` query string, where there's no visible
        # password field initially. The default password-field-only
        # `is_logged_out` therefore reads "still logged in" and the keepalive
        # skips the re-login. Recognising the redirect marker fixes the
        # blind spot. The form IS rendered on that page once MUI hydrates,
        # so we don't need a separate login_url nav.
        "logged_out_url_marker": "?redirect=",
        # MUI form uses `<input type="text" name="email">` for the username
        # — generic selectors miss it (it's not type=email, and `name`
        # doesn't contain `user`/`login`). Be explicit so _do_login fills
        # the right field instead of timing out for 30 seconds. Password
        # field uses standard name='password'.
        "fields": {
            "user":   "input[name='email']",
            "passwd": "input[name='password']",
        },
        # The MUI submit button stays disabled until React sees the inputs
        # change via its synthetic event system. Playwright's .fill() only
        # mutates the DOM, so we drive the inputs through the native value
        # setter + input/change/blur events instead.
        "react_form": True,
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


async def is_logged_out(page: Page, portal_key: str | None = None) -> bool:
    """Decide whether the current page indicates a dead session.

    Default heuristic: a visible password field means we're on a login form.

    Per-portal extension: when `portal_key` is given AND its PORTALS entry
    has `logged_out_url_marker` set, a URL substring match also counts as
    logged-out. This handles SPAs / SaaS apps that redirect to a marketing
    or "where do you want to go?" screen on session expiry, where no
    password field is visible (Tekmetric goes to
    `/?redirect=/admin/...` — no form, but absolutely not authenticated).
    Default to None so legacy callers that don't know the portal_key are
    unaffected.
    """
    if portal_key:
        cfg = PORTALS.get(portal_key) or {}
        marker = cfg.get("logged_out_url_marker")
        if marker:
            markers = [marker] if isinstance(marker, str) else list(marker)
            try:
                u = page.url or ""
                if any(m in u for m in markers):
                    return True
            except Exception:
                pass
    return (await _password_field(page)) is not None


async def _react_fill(page: Page, selector: str, value: str) -> bool:
    """Fill a value into a React-controlled input via the native setter.

    Playwright's `Locator.fill()` types into the DOM but does not always
    trip React's controlled-input state — MUI forms (Tekmetric, modern
    SaaS) keep their submit button disabled because they think the field
    is empty. Going through the prototype's native value setter and
    firing input/change/blur events mirrors what a real keystroke does
    and unlocks the enabled state.

    Returns True on success, False if the selector didn't match.
    """
    try:
        ok = await page.evaluate(
            """({sel, val}) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                el.focus();
                const proto = el.tagName === 'TEXTAREA'
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(el, val); else el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));
                return true;
            }""",
            {"sel": selector, "val": value},
        )
        return bool(ok)
    except Exception as e:
        logger.warning(f"[auth] react_fill failed for {selector!r}: {e}")
        return False


async def _do_login(page: Page, cfg: dict) -> bool:
    user = getattr(settings, cfg["user"], "") or ""
    pw = getattr(settings, cfg["passwd"], "") or ""
    if not user or not pw:
        logger.error(f"[auth] missing credentials for {cfg['user']} / {cfg['passwd']} "
                     f"— add them to .env on the VPS")
        return False

    fields = cfg.get("fields") or {}
    # Detect whether a login form is present. Prefer the portal's explicit
    # password selector — some forms (Worldpac) use <input type="text"
    # name="password">, which the generic type=password probe never sees, so
    # the old `pw_field is None -> already logged in` bail skipped login.
    pw_field = await _password_field(page)
    explicit_pw_sel = fields.get("passwd")
    if explicit_pw_sel:
        try:
            form_present = await page.locator(explicit_pw_sel).count() > 0
        except Exception:
            form_present = pw_field is not None
    else:
        form_present = pw_field is not None
    if not form_present:
        return True  # already logged in
    # React-controlled MUI forms (Tekmetric) keep the submit button
    # disabled until the input's React state matches what's in the DOM.
    # Playwright's .fill() only updates the DOM. When `react_form` is set,
    # we use the native value setter + input/change/blur events instead so
    # React picks up the value and enables the submit.
    use_react = bool(cfg.get("react_form"))

    # Username — prefer explicit per-portal selector, else fall back to generic.
    try:
        user_sel = fields.get("user") or _USER_SEL
        if use_react and fields.get("user"):
            ok = await _react_fill(page, fields["user"], user)
            if not ok:
                logger.warning(f"[auth] react_fill missed user selector "
                               f"{fields['user']!r} — falling back to .fill")
                ufield = page.locator(user_sel).first
                await ufield.fill("")
                await ufield.fill(user)
        else:
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
            if use_react:
                ok = await _react_fill(page, fields["passwd"], pw)
                if not ok:
                    await page.locator(fields["passwd"]).first.fill(pw)
            else:
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
    # When the submit never fired AND a reCAPTCHA challenge iframe is
    # present, the form is locked behind a human-only puzzle. Surface that
    # explicitly so the operator gets one clear "go log in via noVNC"
    # signal instead of cycling through indistinct relogin_failed
    # messages — Tekmetric falls into this state when it detects automated
    # access patterns.
    try:
        recaptcha_challenge = await page.evaluate(
            """() => {
                const frames = Array.from(document.querySelectorAll('iframe'));
                return frames.some(f => (f.src || '').includes('/recaptcha/api2/bframe')
                    && (f.title || '').toLowerCase().includes('challenge'));
            }"""
        )
        if recaptcha_challenge:
            logger.error(
                "[auth] reCAPTCHA challenge active on login form — "
                "automated login cannot solve this; operator must log in "
                "manually via noVNC (port 6080) to clear the challenge and "
                "seed a fresh session cookie"
            )
    except Exception:
        pass
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
            if not await is_logged_out(page, portal_key):
                return {"portal": portal_key, "ok": True, "action": "already_logged_in"}

            # When the logged-out marker fired BUT no password field is
            # currently visible (the marketing-redirect case), the actual
            # login form usually lives at a different URL. Navigate there
            # so _do_login has a real form to drive.
            login_url = cfg.get("login_url")
            if login_url and (await _password_field(page)) is None:
                logger.info(f"[auth] {portal_key}: redirected to logged-out URL "
                            f"({page.url[:80]}); navigating to {login_url} for form")
                try:
                    await page.goto(login_url, wait_until="domcontentloaded",
                                    timeout=20000)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[auth] {portal_key}: login_url nav failed: {e}")

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
