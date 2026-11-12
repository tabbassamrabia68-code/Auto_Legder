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
py -m venv .\AutoLedger_Local_Starter\.venv
& .\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pip install -r .\AutoLedger_Local_Starter\requirements.txt
```

Edit `.env` and provide `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD`. Generate and store a local JWT key without printing it:

```powershell
& .\AutoLedger_Local_Starter\.venv\Scripts\python.exe -c "import secrets; from dotenv import set_key; set_key('.env', 'AUTH_SECRET_KEY', secrets.token_urlsafe(48), quote_mode='never')"
```

The key stays in `.env`, which is ignored by Git. The application refuses to
start with a missing or too-short key rather than silently issuing tokens that
will become invalid after a restart.

Do not overwrite an existing `.env` during setup. If this file is absent,
copy the example once; otherwise preserve the existing connection settings:

```powershell
if (-not (Test-Path .\.env)) {
  Copy-Item .\AutoLedger_Local_Starter\.env.example .\.env
}
```

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
The full route summary is in [API_REFERENCE.md](docs/API_REFERENCE.md).

- `GET /api/health` — real database `SELECT 1` health check
- `POST /api/auth/bootstrap`, `POST /api/auth/login`, `POST /api/auth/register`
- `GET|PATCH /api/auth/me`, `POST /api/auth/password`, `POST /api/auth/refresh`,
  `POST /api/auth/logout`
- `GET /api/auth/roles`, `PUT /api/auth/roles/{role_id}/permissions`
- `GET /api/dashboard`, `GET /api/search?q=...`
- `GET /api/vehicles` — filters, sort, and pagination
- `POST /api/vehicles`, `GET|PUT|DELETE /api/vehicles/{vehicle_id}`
- `GET /api/vehicles/{vehicle_id}/history`
- `POST /api/vehicles/{vehicle_id}/transfer` — calls the atomic SQL function
- `GET /api/reports/vehicles/{vehicle_id}.pdf` — generated vehicle history PDF
- `GET /api/records/{resource}` and `GET /api/records/{resource}/{record_id}`
- `POST /api/records/{resource}`, `PATCH /api/records/{resource}/{record_id}`,
  and Super Admin-only `DELETE /api/records/{resource}/{record_id}` for mutable shared ledger resources
- `GET|POST /api/auth/users`, `GET|PATCH /api/auth/users/{user_id}` (Super Admin only; business-scoped membership management is not implemented)
- `GET /api/reports/vehicles.csv` — optional brand and created-date filters
- `GET|POST|PATCH /api/suppliers`, `/api/customers`
- `GET|POST /api/purchases`, `/api/sales`, `/api/inventory`, and `/api/payments`
- `GET /api/reports/financial`, sale invoice PDF, and payment receipt PDF
- `GET /api/auth/businesses` — active memberships and effective role permissions

Commerce routes require the Phase 4 schema, which is installed on the current
local `autoledger_dev_clone` target only. The original `autoledger_db` remains
unchanged. The application policy defines seven active roles; legacy users
are not automatically reassigned. Commerce APIs now resolve active business
memberships and filter data by the selected `X-Business-ID`. Business/member
administration and tenant-aware database triggers are still incomplete.
Do not use this application as a production shared multi-tenant deployment
until those gaps and broader cross-business checks are complete. See
[FINAL_PROJECT_AUDIT.md](docs/FINAL_PROJECT_AUDIT.md) and
[ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md](docs/ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md).
The current role permission matrix is in
[ROLE_PERMISSION_MATRIX.md](docs/ROLE_PERMISSION_MATRIX.md).

## Database Design

The existing schema and relationships are documented in
[DATABASE_ARCHITECTURE.md](docs/DATABASE_ARCHITECTURE.md) and
[ER_DIAGRAM.md](docs/ER_DIAGRAM.md). Proposed commerce and authentication
extensions are documented in
[PHASE_4_DATABASE_DESIGN.md](docs/PHASE_4_DATABASE_DESIGN.md) and
[PHASE_7_BACKEND_REPORT.md](docs/PHASE_7_BACKEND_REPORT.md). Drafts in
`db/proposed_phase4/` and `db/proposed_phase7/` are not live migrations and
must not be executed without review and approval. Reporting views and
constraints are documented in [ER.md](docs/ER.md). Twelve examples of joins, aggregates,
subqueries, window functions, and CTEs are in [queries.sql](docs/queries.sql).
Measured before/after `EXPLAIN ANALYZE` output is in
[INDEX_PERFORMANCE.md](docs/INDEX_PERFORMANCE.md). PostgreSQL chooses a
sequential scan for the small 76-row service table, which is cheaper at the
current sample size; the composite index remains available as data grows.

## Tests

Database tests write test records. The recommended target is a fresh
disposable database with an `autoledger_test_` name. The current authorized
`autoledger_dev_clone` can be used only with the explicit safety opt-in below;
it accumulates test data. The fixture always refuses `autoledger_db` and
removes `DATABASE_URL` so the target is the verified local PostgreSQL host
and port.

```powershell
$env:AUTOLEDGER_TEST_DB_NAME = 'autoledger_dev_clone'
$env:AUTOLEDGER_ALLOW_DEV_CLONE = '1'
& .\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pytest .\AutoLedger_Local_Starter\tests -v
Remove-Item Env:\AUTOLEDGER_TEST_DB_NAME,Env:\AUTOLEDGER_ALLOW_DEV_CLONE
```

Current results and coverage are in
[PHASE_8_TEST_REPORT.md](docs/PHASE_8_TEST_REPORT.md).

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
   its history PDF, then show the Super Admin-only audit trail and SQL query examples.

## Safety Notes

- `.env`, `.venv`, `node_modules`, local database dumps, caches, and zip files are ignored by Git.
- Never run proposed SQL migrations against the existing database without a
   separate approval and a verified pre-migration backup.
- Do not run the reset/reseed helper against the existing database during normal
   startup or testing. Back up before any planned schema change.
- Keep PostgreSQL bound to localhost for this classroom/demo setup.
- Deployment is not configured. See
   [PHASE_9_DEPLOYMENT_READINESS.md](docs/PHASE_9_DEPLOYMENT_READINESS.md);
   Docker preparation is not a deployment approval.
