# Estimaro Agent (Hermes + Gemini Hybrid)

Vision-driven automation worker that runs on the VPS and produces accurate estimates from logged-in vendor portals.

## Architecture

```
Customer complaint
  -> Hermes 3 (local)    parse to JobSpec
  -> NHTSA vPIC          VIN decode (free)
  -> Gemini 2.5 Flash    vision-driven portal navigation
  -> Hermes 3 (local)    verify each extraction
  -> Cross-source        median / consensus
  -> Result + confidence
```

## One-time Setup (VPS, Windows)

1. Install Python 3.11 from python.org (check "Add to PATH")
2. Install Ollama from https://ollama.com/download/windows
3. `ollama pull hermes3:8b`
4. Copy this entire folder to `C:\Users\Administrator\EstimaroAgent`
5. Run `setup.bat` (creates venv + installs deps + Playwright Chromium)
6. Copy `.env.example` to `.env`, fill in `GEMINI_API_KEY`
7. Get Gemini key free at https://aistudio.google.com/apikey

## Daily Run

### 1. Start logged-in Chrome (once per VPS boot)
```
start_chrome_debug.bat
```
On first launch log into ALLDATA, PartsLink24, SSF, WorldPac, Tekmetric.
Sessions persist in `C:\ChromeDebugProfile`.

### 2. Smoke tests (in order)
```
venv\Scripts\activate
python test_hermes.py     # Hermes JSON output
python test_browser.py    # Chrome debug connect + portal session check
python test_gemini.py     # Gemini vision on current tab
```

### 3. Full pipeline test
```
python main.py
```

## Project Layout

```
EstimaroAgent/
  config.py              .env-backed settings
  main.py                end-to-end pipeline runner
  setup.bat              one-time setup
  start_chrome_debug.bat launches Chrome with --remote-debugging-port=9222

  models/job_spec.py     Pydantic models (JobSpec, VehicleFingerprint, LaborResult, etc.)

  core/
    hermes_client.py     local Hermes 3 wrapper (JSON, verification)
    gemini_client.py     Gemini 2.5 Flash wrapper (vision)
    browser.py           Playwright -> existing Chrome via CDP

  services/
    nhtsa_service.py     free VIN decoder
    verification.py      consensus + Hermes judge

  agents/
    base_agent.py        screenshot -> decide -> execute loop
    alldata_agent.py     labor time lookup (Week 1 POC)
```

## What's Next (per file)

- `agents/partslink24_agent.py` - OEM parts lookup
- `agents/ssf_agent.py`         - aftermarket parts pricing
- `agents/worldpac_agent.py`    - WorldPac SpeedDIAL pricing (desktop app, see ScraperService for hooks)
- `worker.py`                   - polls Railway backend for pending jobs
- Backend additions             - new endpoint `POST /api/v1/auto-generate/jobs` + worker queue
```
