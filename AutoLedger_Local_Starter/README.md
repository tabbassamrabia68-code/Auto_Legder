# AutoLedger

AutoLedger is a local vehicle lifecycle ledger for ownership, maintenance,
odometer, inspection, document, and verification records. It uses FastAPI,
PostgreSQL, bcrypt/JWT authentication, and a responsive browser interface.

## Screenshots

Capture presentation screenshots into `docs/screenshots/` after signing in:

- `dashboard.png` — fleet overview and maintenance charts
- `vehicles.png` — searchable registry and filters
- `vehicle-history.png` — lifecycle timeline and mileage chart
- `documents.png` — document expiry statuses

## Local Setup

Requirements: Windows PowerShell, Python 3.10+, and PostgreSQL running locally.
This workspace uses PostgreSQL port `2005`; the project reads connection values
from the workspace-root `.env`.

```powershell
Set-Location 'C:\Users\<you>\Desktop\Auto_legder'
py -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install -r .\AutoLedger_Local_Starter\requirements.txt
Copy-Item .\AutoLedger_Local_Starter\.env.example .\.env
```

Edit `.env` and provide `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD`. Generate and store a local JWT key without printing it:

```powershell
& .\.venv\Scripts\python.exe -c "import secrets; from dotenv import set_key; set_key('.env', 'AUTH_SECRET_KEY', secrets.token_urlsafe(48), quote_mode='never')"
```

The key stays in `.env`, which is ignored by Git. The application refuses to
start with a missing or too-short key rather than silently issuing tokens that
will become invalid after a restart.

For the existing configured database, start the application without running a
reset, reseed, or migration script:

```powershell
Set-Location 'C:\Users\<you>\Desktop\Auto_legder'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Port 8001
```

`-ExecutionPolicy Bypass` applies to that PowerShell process only; it does not
change the machine's execution policy. The server binds to `127.0.0.1:8001`.

Open <http://127.0.0.1:8001>. On first use, set a password for the existing
Admin account shown on the setup screen. Existing user rows are preserved;
their `password_hash` remains null until each account is given a password.
The first Admin password setup is one-time. Create other users from **Team
access** or allow read-only viewers to register from the sign-in screen.

## API Overview

Interactive API documentation: <http://127.0.0.1:8001/docs>

- `GET /api/health` — real database `SELECT 1` health check
- `POST /api/auth/bootstrap`, `POST /api/auth/login`, `POST /api/auth/register`
- `GET /api/dashboard`, `GET /api/search?q=...`
- `GET /api/vehicles` — filters, sort, and pagination
- `POST /api/vehicles`, `GET|PUT|DELETE /api/vehicles/{vehicle_id}`
- `GET /api/vehicles/{vehicle_id}/history`
- `POST /api/vehicles/{vehicle_id}/transfer` — calls the atomic SQL function
- `GET /api/reports/vehicles/{vehicle_id}.pdf` — generated vehicle history PDF
- `GET /api/records/{resource}` and `GET /api/records/{resource}/{record_id}`
- `POST /api/records/{resource}`, `PATCH /api/records/{resource}/{record_id}`,
  and Admin-only `DELETE /api/records/{resource}/{record_id}` for mutable ledger resources
- `GET|POST /api/auth/users`, `GET|PATCH /api/auth/users/{user_id}` (Admin only)
- `GET /api/reports/vehicles.csv` — optional brand and created-date filters

Viewer accounts are read-only. Admins manage users and audit access; Admins
and Inspectors create inspections/verifications; Dealer and Admin roles manage
fleet records. Database constraints provide a second validation layer.

## Database Design

The schema preserves the existing tables and adds an indexed service `cost`
column and `users.password_hash`. SQL changes are in `db/001_*.sql` through
`db/007_*.sql`; reporting views and constraints are documented in
[ER.md](docs/ER.md). Twelve examples of joins, aggregates,
subqueries, window functions, and CTEs are in [queries.sql](docs/queries.sql).
Measured before/after `EXPLAIN ANALYZE` output is in
[INDEX_PERFORMANCE.md](docs/INDEX_PERFORMANCE.md). PostgreSQL chooses a
sequential scan for the small 76-row service table, which is cheaper at the
current sample size; the composite index remains available as data grows.

## Tests

Tests use the configured local PostgreSQL database. Database tests either roll
back their probes or remove only uniquely created test records and their audit
rows. Do not point these tests at production data.

```powershell
\.venv\Scripts\python.exe -m pytest .\AutoLedger_Local_Starter\tests -v
```

## Five-Minute Demo

1. Sign in as Admin and point out the live PostgreSQL connection and dashboard
   KPIs, maintenance-cost chart, make/fuel distribution, and audit activity.
2. Search for a VIN or registration; filter the fleet by make, fuel, year, or
   ownership status. Open a vehicle and walk through owner, service, repair,
   mileage, inspection, document, and verification history.
3. Show the mileage line chart and trust score. Try a reading below the latest
   odometer value and explain that the database trigger rejects it.
4. Open Documents and show expired/near-expiry badges. Transfer ownership and
   point out that the stored function closes the old active record and opens
   the new one atomically, with a partial unique index preventing two active
   owners.
5. Open Reports, filter and download the fleet CSV. Open a vehicle and download
   its history PDF, then show the Admin-only audit trail and SQL query examples.

## Safety Notes

- `.env`, `.venv`, `node_modules`, local database dumps, caches, and zip files are ignored by Git.
- No SQL migration drops a table or deletes existing records.
- Do not run the reset/reseed helper against the existing database during normal
   startup or testing. Back up before any planned schema change.
- Keep PostgreSQL bound to localhost for this classroom/demo setup.
