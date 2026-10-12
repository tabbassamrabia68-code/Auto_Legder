# AutoLedger Audit Summary

## Frontend Pages

The frontend is a single-page application served at `/`; views are selected with
the URL hash rather than separate HTML files.

- Login, first-time Admin setup, and viewer registration
- Dashboard with fleet KPIs, cost and fleet charts, and recent activity
- Vehicle registry with search, filters, sorting, pagination, create, edit, and delete
- Vehicle detail with ownership, service, repairs, mileage, inspections, documents, and verification tabs
- Owners
- Documents and expiry alerts
- Inspections
- Verification
- Reports with filtered CSV export and browser print-to-PDF vehicle history
- Audit trail (Admin only)
- Team access (Admin only)

## Backend Endpoints

- `GET /` serves the application; `GET /static/{path}` serves frontend assets.
- `GET /api/health` checks the database with `SELECT 1`.
- `GET /api/auth/status`, `POST /api/auth/bootstrap`, `POST /api/auth/login`,
  `POST /api/auth/register`, and `GET /api/auth/me` handle authentication.
- `GET /api/auth/users` and `POST /api/auth/users` list and create users.
- `GET /api/dashboard` and `GET /api/search` provide dashboard and global search data.
- `GET /api/vehicles` lists vehicles with search, filters, sorting, and pagination.
- `POST /api/vehicles` creates a vehicle; `GET /api/vehicles/{vehicle_id}` reads one;
  `PUT /api/vehicles/{vehicle_id}` updates one; `DELETE /api/vehicles/{vehicle_id}` deletes one.
- `POST /api/vehicles/{vehicle_id}/transfer` transfers ownership through the SQL function.
- `GET /api/vehicles/{vehicle_id}/history` returns the vehicle and its related ledger history.
- `GET /api/records/{resource}` lists owners, ownership, service, repairs, mileage,
  inspections, documents, verification, and audit records.
- `POST /api/records/{resource}` creates supported owner, service, repair, mileage,
  inspection, document, and verification records.
- `GET /api/reports/vehicles.csv` exports a filtered vehicle summary.
- `GET /docs` and `GET /openapi.json` are provided by FastAPI.

## Findings

- The baseline backend test suite passes: `8 passed` using the configured local database.
- The running app was not available on `127.0.0.1:8001` during this audit. Browser
  console and responsive rendering checks therefore remain unverified.
- Ledger records other than vehicles and users have list/create routes only; they
  do not have complete update/delete CRUD endpoints.
- `GET /api/auth/users` and `POST /api/auth/users` are not paginated, and there are
  no user update/deactivation endpoints.
- Generic record request bodies are dictionaries rather than resource-specific
  Pydantic schemas. Unknown fields are rejected, but field types and required
  values are mostly left to PostgreSQL constraints.
- Role names include `Dealer` in addition to `Admin`, `Inspector`, and
  `Owner/Viewer`; this does not exactly match the requested role set.
- If `AUTH_SECRET_KEY` is empty, the API creates an ephemeral signing key. Tokens
  stop working after a server restart; configure a stable secret in `.env`.
- The CSV report filters by vehicle creation date, not report/ledger activity date.
- The performance document presents specific before/after timings without a
  reproducible capture record. PostgreSQL may choose a sequential scan for this
  small sample database, so measured plans should be captured from the local DB.
- The database migration/test state is checked through tests, but migration
  application and seed counts were not independently verified during this audit.
- No JavaScript console output is written by the frontend code search; runtime
  browser errors and broken interactive links need a browser session to verify.

## Audit Check

From `AutoLedger_Local_Starter`, run:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

The current result is `8 passed`. Start the app before checking `/api/health`,
`/docs`, browser console output, and phone-width layout.