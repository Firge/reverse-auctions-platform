# Runbook (Local / Docker / Online / Offline)

This project has a Django backend (`backend/`) and a Vite+React frontend (`frontend/`).

## What Was Cleaned Up

- Removed unused frontend app variants (`app.tsx`, `app_v2*`, old wrapper files).
- Removed duplicate Vite config (`frontend/vite.config.ts`) to avoid proxy confusion.
- Kept `frontend/vite.config.js` as the single active Vite config.
- Added Vite proxy notes and env override support (`VITE_DEV_API_PROXY`).

## URLs and Ports (Default)

- Backend (Django): `http://127.0.0.1:8000`
- Frontend (Vite dev): `http://127.0.0.1:5173`
- Frontend API calls in dev go to `/api/...` and are proxied to backend.

## Quick Start (Most Reliable on a New Machine)

### Option A: Hybrid (Docker DB/Redis + local backend/frontend)

Use this if Python/Node are installed locally but you do not want to install Postgres/Redis directly on the machine.

1. Start infra:

```powershell
docker compose up -d postgres redis
```

2. Backend setup (PowerShell, from repo root):

```powershell
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
venv\Scripts\python.exe backend\manage.py migrate
venv\Scripts\python.exe backend\manage.py runserver
```

3. Frontend setup:

```powershell
cd frontend
npm install
npm run dev
```

4. Open:

- Frontend: `http://127.0.0.1:5173`
- Backend API check: `http://127.0.0.1:8000/api/auctions/`

### Option B: Full Docker (backend + DB + Redis)

Use this if you want minimum local setup.

```powershell
docker compose up --build web postgres redis
```

Optional workers:

```powershell
docker compose up --build celery_worker celery_beat
```

### Option C: Fully Local (no Docker)

You need local Postgres + Redis installed and running.

Set `backend/.env` to match your local services, then run backend/frontend as in Option A (without `docker compose up`).

## Environment Files

### Backend

- Runtime file: `backend/.env`
- Template: `backend/.env.example`

Important:

- `backend/bidfall/settings.py` loads `backend/.env` explicitly (works even if you run `python backend/manage.py ...` from repo root).

### Frontend (optional)

- Template: `frontend/.env.example`

You can override the Vite proxy target on another machine:

```powershell
$env:VITE_DEV_API_PROXY='http://127.0.0.1:8000'
npm run dev
```

## Online / Offline Scenarios

### 1) Machine Has Internet Access

Recommended:

- `pip install -r backend/requirements.txt`
- `npm install` in `frontend/`
- `docker compose up ...` if using Docker

### 2) Machine Has No Internet Access (Offline)

Important limitation:

- A fresh offline machine cannot install Python/Node dependencies unless you already have cached/preloaded packages.

Working offline approaches:

1. Reuse existing `venv` and `frontend/node_modules` copied from another machine with the same OS/architecture.
2. Use pre-pulled Docker images / prebuilt containers (`postgres`, `redis`, backend image).
3. Use local wheel/npm caches:
   - Python: `pip install --no-index --find-links <wheels_dir> -r backend/requirements.txt`
   - npm: `npm ci --offline` (requires local npm cache / lock compatibility)

## Common Pitfalls

### 1) Frontend says `Unexpected server response`

This means frontend expected JSON but received HTML/text.

Check:

1. Open frontend via Vite dev server (`:5173`), not `dist/index.html`.
2. Backend is running on the port expected by Vite proxy (default `8000`).
3. `frontend/vite.config.js` proxy points to the correct backend host/port.
4. Browser localStorage does not contain stale `bidfall_api_base`.

Reset in browser console:

```js
localStorage.removeItem("bidfall_api_base");
localStorage.removeItem("bidfall_tokens");
location.reload();
```

### 2) Registration “does not work”

Backend registration endpoint is `POST /api/auth/register/` and returns JSON.

Most common causes:

- invalid password (too short / no letters+digits),
- duplicate username/email,
- frontend talking to wrong server/port.

### 3) Migrations fail on a new machine

Checklist:

1. Install **backend** dependencies from `backend/requirements.txt` (not root `requirements.txt`).
2. Ensure Postgres is reachable using values from `backend/.env`.
3. Run:

```powershell
venv\Scripts\python.exe backend\manage.py migrate
```

## Catalog Data (External Tables)

`catalog_*` tables are external/unmanaged and used by auction lot linking.

Tools:

- Schema: `tools/schema.sql`
- Parser: `tools/parse_tssc.py`
- Loader: `tools/load_tssc_to_postgres.py`

Docker profiles for parser/loader are defined in `docker-compose.yaml`:

- `parse`
- `load`
- `pipeline`

Example (pipeline):

```powershell
docker compose up -d postgres
docker compose --profile pipeline run --rm pipeline
```

## Smoke Test Commands

Backend JSON endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/auctions/
```

Frontend proxy path (with Vite running):

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/auctions/
```

## Notes for Team Members

- `frontend/vite.config.js` is the active Vite config (single source of truth).
- `frontend/src/main.tsx` imports `app_market_clean.tsx` as the current UI entry.
- `_new.py` merge-helper files were removed after integrating safe changes.
