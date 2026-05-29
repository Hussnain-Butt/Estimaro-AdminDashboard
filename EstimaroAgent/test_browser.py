"""Verify connection to existing logged-in Chrome on port 9222."""
import asyncio
from core.browser import ChromeDebugBrowser


async def main():
    print("Connecting to Chrome debug session...")
    async with ChromeDebugBrowser() as cb:
        pages = cb.context.pages
        print(f"\nFound {len(pages)} open tabs:")
        for i, p in enumerate(pages):
            print(f"  [{i}] {p.url[:80]}")

        portals = {
            "alldata": "alldata",
            "partslink24": "partslink24",
            "ssf": "ssf",
            "worldpac": "worldpac",
            "tekmetric": "tekmetric",
        }
        print("\nPortal session check:")
        for name, needle in portals.items():
            tab = await cb.find_tab_by_url(needle)
            print(f"  {name:12s} {'OK ' + tab.url[:60] if tab else 'NOT OPEN'}")


if __name__ == "__main__":
    asyncio.run(main())
