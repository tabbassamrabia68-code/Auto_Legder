# AutoLedger Progress Report

Status checked: 2026-10-12. No database schema changes were made in this pass.
Test and browser probes used uniquely identified temporary records and cleaned
their rows and related test audit entries.

## Completed Features

- Authenticated FastAPI application with dashboard, global search, vehicle
  CRUD/history, atomic ownership transfer, generic ledger CRUD for mutable
  resources, CSV reports, and per-vehicle PDF reports.
- Resource-specific Pydantic create/patch validation, allowlisted parameterized
  database operations, FK conflict handling, and transaction boundaries.
- Admin user list/item/create/access update, with a final-active-Admin guard.
- Search, filter, pagination and sorting for the vehicle register; editable
  owner/document/inspection/verification lists and service/repair/mileage
  controls in vehicle history.
- SQL indexes, mileage rollback trigger, document expiry trigger, audit
  triggers, single-active-owner partial unique index, transactional transfer
  function, and four reporting views.
- Twelve read-only showcase SQL queries covering joins, aggregates, window
  functions, CTEs, ownership, verification, and document status.
- Responsive dashboard, vehicle detail, authentication, CSV download and PDF
  download workflows.

## Remaining Limitations

- Generic ownership updates/deletes are intentionally disabled; use the atomic
  transfer workflow so history cannot be rewritten. Roles and audit logs are
  read-only through the API.
- Search/list sorting and pagination are not uniform across every resource;
  user listing is not paginated.
- The final-active-Admin guard is implemented but does not yet have a dedicated
  test. Some less-used screens and actions lack browser automation coverage.
- Existing database roles include legacy `Dealer` and `Verification User`.
- The stated fleet count was 40, while the live count is 41. No pre-change ID
  snapshot exists to explain the difference; all 41 current vehicles remain.
- Historical audit rows use legacy entity labels (`Vehicle`, `Inspection`,
  `Verification`) and action labels. Current triggers are installed and
  enabled, but there are no current-format `vehicles` or `ownership_records`
  audit rows. Past changes cannot be reconstructed from the available log.
- Browser popup printing may be blocked; use the authenticated PDF download
  button instead.

## Application and Database

- Startup: `start.ps1` was tested successfully with the command below. The
  execution-policy bypass applies only to that PowerShell process.
- Health: `GET /api/health` returned `{"status":"ok","database":"connected"}`.
  `/docs`, `/openapi.json`, `/`, and static JavaScript/CSS returned HTTP 200.
- Database: PostgreSQL 18.6 at `localhost:2005`, database `autoledger_db`.
  `.env` has a stable JWT key; its value was not displayed. `.env`, `.venv`,
  `node_modules`, and local dump/backup files are ignored by Git.
- Live counts: 12 base tables, 41 vehicles, 284 owners, 41 ownership records,
  76 services, 38 repairs, 116 mileage records, 40 inspections, 78 documents,
  40 verifications, 7 users, and 50 audit rows. Two earlier browser-smoke viewer
  accounts remain. No test Admins or UI test owners remain.
- No reset, reseed, table drop, truncate, or migration was run. Counts before
  and after verification match; no pre-existing vehicle or ledger row was
  intentionally changed or removed. This is count-based confirmation, not a
  row-by-row comparison against an unavailable baseline snapshot.

## Verification

- Full pytest suite: **14 passed in 31.21 seconds**.
- Tests cover role/auth checks, protected vehicle reads, duplicate VIN, CRUD,
  FK delete conflicts, dashboard/search/history, filtered CSV, PDF signature,
  transfer failure/success atomicity, mileage rollback, expiry, and audit
  triggers. Test-created rows and audit entries are rolled back or cleaned.
- The mileage test inserts a temporary vehicle and reading, confirms a lower
  reading raises SQLSTATE `23514`, then rolls back the transaction.
- The transfer test uses temporary vehicle/owner rows, confirms an invalid
  earlier date leaves the old owner active, confirms valid transfer closes the
  old row and opens one new active row, then rolls back.
- All twelve showcase queries ran successfully in a PostgreSQL read-only
  transaction. The rollback-detection query returned zero current anomalies.
- CSV output matched a read-only SQL query using the same brand and creation-date
  filters. PDF output is 4,356 bytes with `%PDF-1.4` header and `%%EOF` trailer.
  The UI PDF action received HTTP 200 and displayed its success state.
- Pylance reported no errors in touched Python files. `node` is not installed;
  browser compilation and runtime checks validated the frontend bundle instead.
- The final-active-Admin scenario and some less-used browser actions remain
  unverified. Popup-based printing was blocked in the integrated browser; direct
  PDF download is verified.

## Midterm Demo Commands

Start the app and open the dashboard:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Port 8001
Start-Process 'http://127.0.0.1:8001/#dashboard'
```

Demo flow: sign in; show dashboard totals and search/filter the vehicle list;
open a vehicle and show owner/service/mileage tabs; explain the SQL transfer
function and partial unique index; show the mileage-trigger rejection; run the
12 read-only statements in `docs/queries.sql`; filter **Reports** by make/date
and download CSV; download the vehicle-history PDF from vehicle detail.

Open the verified report files created in this pass:

```powershell
Invoke-Item 'C:\Users\rabia tabbassam\Desktop\AutoLedgerBackups\AutoLedger_Toyota_2026.csv'
Invoke-Item 'C:\Users\rabia tabbassam\Desktop\AutoLedgerBackups\AutoLedger_Vehicle_1_History.pdf'
```

No database schema changes were needed or applied.