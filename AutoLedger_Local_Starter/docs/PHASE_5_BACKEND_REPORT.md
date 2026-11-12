# AutoLedger Phase 5 Backend Report

**Status:** Backend implementation complete; database-dependent commerce
operations are gated until a separately approved migration is applied.
**Database migrations were not executed.**

## 1. Inspection performed

Before implementation, the existing FastAPI backend, database connection
loader, authentication and role dependencies, record routes/schemas/services,
test suite, Phase 4 design, proposed ER diagram, and database architecture
were reviewed.

A read-only catalog check against the configured live PostgreSQL 18.6 database
confirmed:

- Host `localhost`, configured port `2005`, database `autoledger_db`.
- 16 base tables, 95 base-table columns, 16 primary keys, 14 foreign keys,
  5 unique constraints, 14 check constraints, 46 indexes, 4 views, and 13
  named row triggers.
- 41 vehicles, 41 ownership rows, 316 audit rows, 2 suppliers, 2 customers,
  and zero purchase and sales headers at inspection time.
- `purchase_items`, `sale_items`, `vehicle_inventory`, and `payments` are not
  present in the live schema.

The existing vehicle, ownership, and vehicle-history tables are reused without
changing their schema or records. No existing vehicle was assigned an
invented purchase or inventory status.

## 2. Implemented backend modules

- Supplier and customer create/list/detail/update APIs using their existing
  tables. API writes add audit rows to the existing `audit_logs` table.
- Purchase workflow creates a draft header and per-vehicle lines, calculates
  the header total from line prices, then transitions through ordered to
  received in one transaction. The proposed database receipt trigger adds
  inventory state.
- Sale workflow locks the selected vehicle and inventory rows in ascending
  vehicle ID order, verifies every vehicle is available, creates the sale and
  lines, calculates the total, transitions through confirmed to completed,
  and optionally records an initial payment in the same transaction. Any
  exception rolls back the complete operation.
- Inventory listing includes untracked legacy vehicles without assigning a
  status. Explicit onboarding requires a source note; status changes are
  limited to `AVAILABLE` and `UNDER_MAINTENANCE`. Sale transitions are managed
  by the transaction workflow.
- Payment APIs record completed, pending, or failed payments; pending payments
  can be completed, failed, or voided. Balances use completed payment events;
  pending payments reserve remaining capacity to avoid concurrent
  over-allocation. Amount checks serialize on the transaction header row.
- PKR is fixed for payment records. Tax is disabled; sale requests with a
  nonzero tax amount are rejected.
- Customers remain separate from owners. Sale completion does not edit
  `ownership_records`.

All commerce routes first validate the presence of the proposed columns and
workflow/audit triggers. Until the migration is separately approved and
applied, purchase, sale, inventory, and payment routes return HTTP 503 rather
than silently using an incomplete schema. Supplier/customer routes use the
existing schema and are available.

## 3. API routes

All routes require bearer authentication. `Admin` and `Dealer` can manage
purchase, sale, inventory, and payment workflows. `Admin` alone manages
supplier/customer records. `Dealer`, `Inspector`, and `Owner/Viewer` can read
reference data, transactions, payments, and inventory. `Verification User` is
denied access until a policy is explicitly assigned.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/suppliers` | Search/list suppliers |
| POST | `/api/suppliers` | Create supplier (Admin) |
| GET | `/api/suppliers/{supplier_id}` | Supplier details |
| PATCH | `/api/suppliers/{supplier_id}` | Update supplier (Admin) |
| GET | `/api/customers` | Search/list customers |
| POST | `/api/customers` | Create customer (Admin) |
| GET | `/api/customers/{customer_id}` | Customer details |
| PATCH | `/api/customers/{customer_id}` | Update customer (Admin) |
| GET | `/api/purchases` | Purchase history with paid and due totals |
| POST | `/api/purchases` | Receive a multi-vehicle purchase, optional initial payment |
| GET | `/api/purchases/{purchase_id}` | Purchase and line-item details |
| GET | `/api/sales` | Sales history with paid and due totals |
| POST | `/api/sales` | Complete a multi-vehicle sale, optional initial payment |
| GET | `/api/sales/{sale_id}` | Sale and line-item details |
| GET | `/api/inventory` | Search/filter stock, including `UNTRACKED`, plus valuation |
| POST | `/api/inventory/{vehicle_id}` | Explicitly onboard a vehicle with source evidence |
| GET | `/api/inventory/{vehicle_id}` | Current stock status and vehicle details |
| PATCH | `/api/inventory/{vehicle_id}` | Move between available and maintenance |
| GET | `/api/payments` | Payment history, optionally filtered by purchase or sale |
| POST | `/api/payments` | Record a payment against exactly one purchase or sale |
| GET | `/api/payments/{payment_id}` | Payment details |
| PATCH | `/api/payments/{payment_id}` | Settle or close a pending payment |

Request models reject unknown fields, invalid references, duplicate vehicles
within a transaction, invalid money precision/amounts, and unsupported tax.
Database uniqueness/FK/check conflicts are returned as safe conflict or
validation responses; missing commerce schema is reported as 503.

## 4. Database and migration status

The Phase 4 SQL files under `db/proposed_phase4/` remain **PROPOSED — NOT
EXECUTED**. They were updated to reflect the approved PKR/no-tax settings and
evidence-backed inventory onboarding. The backend checks for the tables,
columns, and trigger names before enabling database-dependent routes.

The proposals have not been executed against either the live database or the
isolated test database. Live schema and business data were not modified.
Supplier/customer API writes against the test clone created by the test run
were confined to that isolated database.

The existing `purchases.total_amount` and `sales.total_amount` fields are
maintained from line-item totals. `payments` is proposed as an event ledger;
settled balances are derived and pending attempts do not count as money
received. The API does not expose refunds yet.

## 5. Security, permissions, and audit

- All new routes use the existing JWT authentication and `require_roles`
  dependency.
- SQL values are parameterized. Dynamic SQL identifiers are selected only
  from fixed, internal table/column names.
- Supplier/customer changes write field-name-only audit details, avoiding
  placing submitted contact values into these application-generated audit
  entries.
- Transaction, item, inventory, and payment audit events depend on the
  proposed audit triggers using transaction-local `app.user_id`.
- The existing ownership transfer and history mechanisms are untouched.
- `Verification User` is not included in the allowlists.

## 6. Testing results

The existing full backend suite and new Phase 5 checks were run against a
separate PostgreSQL 18.6 database named
`autoledger_test_phase5_20261107_195132`, restored from the previously
verified backup. The test target used the same configured host and port 2005
but a different database name. Pytest now refuses to run unless
`AUTOLEDGER_TEST_DB_NAME` names a separate database beginning with
`autoledger_test_` and does not match the configured live database.

**Result: 22 passed, 4 skipped.** The four commerce integration tests are
present but skip unless all proposed columns and workflow/audit triggers are
installed in the isolated test database.

Repeat with the dedicated isolated test database configured in PowerShell:

```powershell
$env:AUTOLEDGER_TEST_DB_NAME = "autoledger_test_phase5_20261107_195132"
.\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pytest .\AutoLedger_Local_Starter\tests -q
```

Coverage included existing auth, vehicle, ownership, audit, reports, and
database-feature regression tests; supplier/customer CRUD and audit logging;
schema/request validation; role restrictions; and fail-closed behavior when
proposed commerce tables/triggers are absent.

Purchase/sale/payment/inventory transaction integration tests were collected
but skipped because the proposed schema is intentionally absent from the
isolated database and migration execution is not approved. The tests cover
purchase totals/inventory/payment, partial and full sale payment, duplicate
sale prevention, transactional rollback, and concurrent attempts to sell one
vehicle; they must be run against the proposed schema on an isolated database
after a separate migration approval and before deployment. Current routes
were verified to fail closed with 503. Existing-function regression tests
passed on the isolated copy.

## 7. Changed files

- Added `backend/commerce.py`.
- Added `backend/commerce_schemas.py`.
- Updated `backend/main.py` to register the commerce router.
- Updated `tests/conftest.py` to require a dedicated test database.
- Added `tests/test_commerce_api.py`.
- Updated the Phase 4 proposals:
  - `db/proposed_phase4/001_purchase_design.sql`
  - `db/proposed_phase4/002_sales_design.sql`
  - `db/proposed_phase4/003_vehicle_inventory_design.sql`
  - `db/proposed_phase4/004_payments_design.sql`
  - `db/proposed_phase4/005_lifecycle_and_audit_triggers_design.sql`
- Updated `docs/PHASE_4_DATABASE_DESIGN.md` and
  `docs/PHASE_4_PROPOSED_ER_DIAGRAM.md` to reflect the approved currency,
  tax, and inventory-evidence rules.
- Added `docs/PHASE_5_BACKEND_REPORT.md`.

Previously staged and unstaged work was preserved; no commit or push was made.

## 8. Known limitations and remaining work

1. The four proposed commerce tables and purchase/sale header extensions need
   a final migration review and separate approval before execution.
2. The current live database will return 503 for purchase, sale, inventory,
   and payment APIs until that migration is applied.
3. Refund creation, refund validation, and provider idempotency are not
   implemented.
4. No sales tax is implemented; tax must remain zero until a separately
   approved tax policy and migration/API design exist.
5. Purchase/sale header list endpoints currently return all matching headers;
   pagination should be considered before production-scale use.
6. Opening stock is individually entered with evidence; no bulk status or
   historical purchase backfill is performed.
7. Phase 6 frontend work has not started.

Before a live migration, review the additive SQL, create a fresh verified
backup, perform a restore drill, test the proposed schema and all transactional
workflows on an isolated database, and request separate explicit approval.
