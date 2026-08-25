# Estimaro Admin Dashboard

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?style=flat&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-7-646CFF?style=flat&logo=vite&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?style=flat&logo=postgresql&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-3-06B6D4?style=flat&logo=tailwindcss&logoColor=white)

Estimaro is an automation platform for auto-repair shops that turns a customer's VIN and job description into a priced, vendor-sourced repair estimate — VIN decode, recall and warranty checks, labor-time and OEM-parts lookup, vendor price comparison, and a customer-facing approval link, ending with the finished estimate pushed into **Tekmetric**.

This repository is the platform monorepo. It contains the React **admin dashboard** the repo is named for, plus the FastAPI backend and automation services that power it.

## Repository Structure

| Path | Description |
|---|---|
| [`Frontend/`](./Frontend) | React + Vite admin dashboard — advisor UI, reporting, and the customer approval page |
| [`Backend/`](./Backend) | FastAPI + PostgreSQL REST API — estimates, customers, vehicles, vendors, Tekmetric integration |
| [`EstimaroAgent/`](./EstimaroAgent) | Vision-driven automation worker (local LLM + Gemini) that reads vendor portals through a real, logged-in Chrome session |
| [`ScraperService/`](./ScraperService) | Standalone FastAPI microservice that scrapes vendor sites over the Chrome DevTools Protocol |
| [`deploy/`](./deploy) | Batch scripts and environment templates for standing up the stack on a Windows VPS/RDP host |
| [`Estimaro-Automation-Workflow.md`](./Estimaro-Automation-Workflow.md) | Full write-up of the automated estimation pipeline — steps, data shapes, and scoring formulas |

Each folder above has its own `README.md` with module-specific setup steps; this file covers the platform as a whole.

## How an Estimate Gets Built

The backend implements the pipeline documented in `Estimaro-Automation-Workflow.md` as a set of discrete services under `Backend/app/services/`:

1. **VIN decode** (`vin_decoder_service.py`) — resolve year/make/model/trim from the VIN
2. **Recall check** (`recall_service.py`) — flag open recalls before work begins
3. **Warranty check** (`warranty_service.py`) — flag vehicles likely still under factory warranty
4. **Labor lookup** (`labor_service.py`) — official labor hours, sourced from ALLDATA via a scraper adapter (with a mock adapter for local development)
5. **Auto add-on detection** (`addon_service.py`) — rule-based detection of parts a procedure implies (gaskets, fluids, etc.)
6. **OEM parts matching** (`parts_service.py`) — VIN + description → OEM part numbers, via PartsLink24
7. **Vendor pricing & scoring** (`vendor_service.py`) — weighted price/brand/distance comparison across Worldpac and SSF
8. **Part condition disclosure** (`part_condition_service.py`) — flags parts as New vs. Remanufactured from vendor descriptions
9. **Estimate calculation** (`calculation_service.py`) — labor + marked-up parts + tax
10. **Advisor review** — a human checkpoint in the dashboard's Review Queue before anything goes out
11. **Customer approval** (`approval_service.py`) — a no-login approval link the customer can act on directly
12. **Tekmetric push** (`tekmetric_service.py`) — creates the repair order in Tekmetric once approved

Vendor-portal access (steps 4, 6, 7) is handled two ways in this repo: lightweight Playwright adapters inside the Backend itself (`Backend/app/adapters/`), and — for the harder, JS-heavy portals — a separate, vision-driven worker (`EstimaroAgent`) that drives an already-logged-in Chrome instance and uses Gemini 2.5 Flash to read the screen. Per `EstimaroAgent/README.md`, the ALLDATA labor-lookup agent is implemented; PartsLink24, SSF, and Worldpac agents and the backend job-polling worker are the next pieces to land.

## Dashboard Features

From `Frontend/src/components/`:
- Dashboard analytics overview and Reports (Chart.js / Recharts)
- Customer management
- Multi-step New Estimate builder (`estimate-steps/`)
- Vendor management
- Review Queue for advisor sign-off
- Feedback Review, including a standalone voice assistant page ("Talk to Assistant") built on the ElevenLabs Conversational AI SDK
- Customer Approval page — the public, no-login view a customer opens from their approval link
- PDF export (jsPDF) and shop Settings

## Tech Stack

| Service | Stack |
|---|---|
| **Frontend** | React 19, Vite 7, Tailwind CSS, React Router, Chart.js / Recharts, ElevenLabs React SDK, jsPDF, GSAP |
| **Backend** | FastAPI, SQLAlchemy 2 + PostgreSQL, Alembic migrations, Pydantic v2, JWT auth (python-jose), Playwright, Twilio (SMS); MongoDB via Motor/Beanie is also a listed dependency |
| **EstimaroAgent** | Python, FastAPI, Playwright, Google Gemini 2.5 Flash (vision), local Hermes 3 via Ollama, Pydantic |
| **ScraperService** | FastAPI, Playwright, PyAutoGUI / pywinauto (Worldpac desktop-app automation), Gemini, RapidFuzz |

## Getting Started

These steps bring up the dashboard against the API locally. See `EstimaroAgent/README.md`, `ScraperService/README.md`, and `deploy/README.md` for the automation workers, which are designed to run on a Windows host with a persistent, logged-in Chrome session.

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15 (or Docker, via `Backend/docker-compose.yml`)
- Optional, for `EstimaroAgent`: [Ollama](https://ollama.com) with the `hermes3:8b` model, and a Gemini API key

### 1. Backend API

```bash
cd Backend
python -m venv venv
.\venv\Scripts\Activate.ps1      # Windows PowerShell

pip install -r requirements.txt

copy .env.example .env           # then edit .env — set SECRET_KEY, DB URL, etc.

docker-compose up -d             # starts PostgreSQL (+ pgAdmin)
alembic upgrade head

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs` · ReDoc: `http://localhost:8000/redoc`

### 2. Frontend Dashboard

```bash
cd Frontend
npm install
npm run dev
```

### 3. Automation workers (optional)

`EstimaroAgent` and `ScraperService` each ship a `setup.bat` and expect a Chrome instance already logged into ALLDATA, PartsLink24, Worldpac, SSF, and Tekmetric (`start_chrome_debug.bat`). See their individual READMEs for the full walkthrough.

## Configuration

Each service reads its own `.env`. At minimum you'll need:

- **Backend** — database URL, JWT `SECRET_KEY`, Twilio credentials (for SMS notifications)
- **EstimaroAgent** — `GEMINI_API_KEY`, Ollama host, vendor-portal credentials (ALLDATA / PartsLink24 / Worldpac / SSF), Tekmetric API key
- **deploy** — `.env.production.template` covers the combined configuration for a single-host production deployment

Only `.example` / `.template` files belong in the repo — never commit a filled-in `.env`.

## Deployment

`Backend` and `Frontend` each include a `railway.json` / `nixpacks.toml` for deployment on Railway. `EstimaroAgent` and `ScraperService` are built to run on a Windows VPS/RDP host that keeps a real, logged-in Chrome session open for the vendor portals — see `deploy/README.md` for the step-by-step server setup.

## Project Status

Under active development. Per the module READMEs: the Backend's foundation (schema, migrations, Docker setup) is in place with core estimation services implemented, and `EstimaroAgent` currently ships its ALLDATA labor-lookup agent, with PartsLink24, SSF, and Worldpac agents plus the backend job-polling worker still to come.

## License

No license file is currently included in this repository.
