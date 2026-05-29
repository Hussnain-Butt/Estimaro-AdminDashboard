"""Verify Gemini API connectivity + vision capability."""
import asyncio
from core.gemini_client import GeminiClient
from core.browser import ChromeDebugBrowser


async def main():
    print("=" * 60)
    print("GEMINI FLASH SMOKE TEST")
    print("=" * 60)

    gem = GeminiClient()
    print(f"Model: {gem.model_name}")

    print("\nGrabbing screenshot from active Chrome tab...")
    async with ChromeDebugBrowser() as browser:
        if not browser.context.pages:
            print("No tabs open in debug Chrome. Open ALLDATA first.")
            return
        page = browser.context.pages[0]
        shot_bytes, shot_path = await browser.screenshot(page, label="gemini_test")
        print(f"Screenshot saved: {shot_path}")
        print(f"Current URL: {page.url}")

    print("\nAsking Gemini to describe the page...")
    result = gem.extract_from_screenshot(
        shot_bytes,
        fields=["page_title", "main_heading", "visible_buttons", "form_fields"],
    )
    import json
    print(json.dumps(result, indent=2))

    print("\nGemini vision pipeline working.")


if __name__ == "__main__":
    asyncio.run(main())
