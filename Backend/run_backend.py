import sys
import asyncio
import uvicorn

# WIN32 FIX: Force WindowsProactorEventLoopPolicy for Playwright
# This MUST be done before any async loop is created.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    print("🚀 Starting Estimaro Backend with scraping support...")
    print("NOTE: Auto-reload is disabled to ensure scraping compatibility.")
    # reload=False is required because reload spawns a subprocess that resets the event loop policy
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
