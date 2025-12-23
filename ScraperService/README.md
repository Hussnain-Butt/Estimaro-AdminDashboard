# Estimaro Scraper Service

Microservice for scraping vendor websites via Chrome CDP.
Runs on Windows RDP server where Chrome is logged into vendor sites.

## Quick Setup

1. Run `setup.bat` to install dependencies
2. Start Chrome in debug mode (run `start_chrome_debug.bat` from deploy folder)
3. Run `start_service.bat` to start the service

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check + Chrome status |
| `/scrape/labor` | POST | Get labor time from ALLDATA |
| `/scrape/parts` | POST | Get OEM parts from PartsLink24 |
| `/scrape/pricing` | POST | Get pricing from Worldpac/SSF |

## Authentication

All `/scrape/*` endpoints require API key header:
```
X-API-Key: your_api_key
```

## Example Usage

```bash
curl -X POST http://windows-rdp-ip:5000/scrape/labor \
  -H "Content-Type: application/json" \
  -H "X-API-Key: estimaro_scraper_secret_2024" \
  -d '{"vin": "1HGBH41JXMN109186", "job_description": "Brake pads"}'
```
