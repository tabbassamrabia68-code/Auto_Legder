# AutoLedger Phase 8 — Test and Verification Report

## Test environment

- Application: existing FastAPI project and virtual environment.
- Database target: isolated `autoledger_test_master_20261107_2045`, restored
  from the verified backup; configured host and port were `localhost:2005`.
- The target name was checked against the configured live database and its
  existence confirmed before running tests.
- No database test used `autoledger_db`.
- The isolated clone contains restored baseline data, proposed Phase 4/7
  schema for testing, and test-generated records. Its Phase 7 permission
  rows predate the final proposed role-grant edits; the suite separately
  verifies the current Python defaults and route-level access behavior.
  Restore a fresh isolated clone before treating it as a clean test fixture.

## Automated results

Command:

```powershell
Set-Location .\AutoLedger_Local_Starter
$env:AUTOLEDGER_TEST_DB_NAME='autoledger_test_master_20261107_2045'
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **28 passed in 36.48 seconds**.

Coverage exercised by the suite includes:

- Authentication, viewer registration, password hashing, refresh-token
  rotation/replay rejection, password-change invalidation, and logout.
- Admin/Super Admin separation, default role permission policy, and role
  permission endpoint access.
- Read-only Inspector/Owner restrictions and Verification User denial.
- Existing vehicle search, details, history, dashboard, CSV and PDF behavior.
- Supplier/customer CRUD and audit history.
- Purchase totals, inventory onboarding, partial/full settlements, sale
  completion, duplicate-sale rejection, concurrent sales, payment
  idempotency, and transaction rollback.
- Financial report and PDF invoice/receipt generation.
- Request validation and database integrity error handling.

Python `compileall` passed for `backend` and `tests`. `git diff --check` was
also run during verification. Node.js and Docker are not installed in this
environment; JavaScript syntax and browser behavior were checked in Chromium.

## Browser checks

The app was started on `127.0.0.1:8001` with a process-local database override
pointing to the isolated test clone; the workspace `.env` was not changed.
`/api/health` and the app root returned HTTP 200.

Using a temporary Admin account in the isolated clone:

- Real login and dashboard loading succeeded.
- The responsive mobile navigation opened, routed to Reports, and closed.
- The financial report loaded real isolated-clone transaction totals and
  rendered PKR values and the missing-acquisition-cost caveat.
- Dark/light theme toggling worked.
- No JavaScript page errors or failed API responses were observed during the
  successful run.

A separate mocked UI login verified that a Verification User sees only
Profile & Settings and an access-pending message; it cannot reach vehicle or
business pages. The backend suite independently verifies those API requests
return `403`.

Browser snapshots were inspected, but no screenshot files were saved to the
repository.

## Production and data integrity checks

The application/browser checks and the test suite were isolated from the live
database. No live schema or business record was modified, no migration or seed
script was run against `autoledger_db`, and no deployment was performed.

## Remaining verification (updated after tenant work)

- The proposed schema has been exercised on an isolated clone but still
  requires DBA review and separate explicit approval before any production
  migration.
- Production migration, backup/restore rehearsal, HTTPS/reverse-proxy
  validation, and live-account permission testing are intentionally pending.
- Business membership creation/revocation, tenant-aware database triggers,
  shared vehicle/history authorization, and browser-level membership
  switching remain incomplete or unverified.

## Supplemental role-policy verification

After the final seven-role permission changes, the full backend suite was
rerun against the same isolated database:

```powershell
$env:AUTOLEDGER_TEST_DB_NAME='autoledger_test_master_20261107_2045'
.\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pytest .\AutoLedger_Local_Starter\tests -q
```

At the prior seven-role verification point: **28 passed in 23.04 seconds**.
Python compilation also passed for `backend` and `tests`.

The local app was then started with a process-only database override pointing
to that isolated clone. A newly registered Viewer signed in successfully;
the dashboard, vehicle/history navigation, reports, and profile were
available, while Inventory, Customers, and Team access were hidden. On a
375-pixel viewport, the mobile menu opened and closed, and the theme toggle
changed the active theme. This browser check did not establish tenant
isolation; shared multi-tenant deployment remains blocked as described in
[ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md](./ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md).

After enforcing Super Admin-only writes for globally shared vehicle and
history records, the isolated suite was rerun:

```powershell
Set-Location .\AutoLedger_Local_Starter
$env:AUTOLEDGER_TEST_DB_NAME='autoledger_test_master_20261107_2045'
.\.venv\Scripts\python.exe -m compileall -q backend tests
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **29 passed in 33.68 seconds**. The targeted role/auth suite also
passed **7 tests**, including API-level checks that Admin cannot mutate shared
vehicle/history records and Super Admin can perform those platform actions.

## Latest membership and commerce isolation verification

The latest run explicitly targeted `autoledger_dev_clone` on localhost:2005;
the test fixture required `AUTOLEDGER_ALLOW_DEV_CLONE=1` and continued to
reject `autoledger_db`.

```powershell
$env:DB_HOST='localhost'
$env:DB_PORT='2005'
$env:DB_NAME='autoledger_dev_clone'
$env:AUTOLEDGER_TEST_DB_NAME='autoledger_dev_clone'
$env:AUTOLEDGER_ALLOW_DEV_CLONE='1'
Set-Location .\AutoLedger_Local_Starter
.\.venv\Scripts\python.exe -m compileall -q backend tests
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: Python compilation passed and **31 tests passed in 110.88 seconds**.
Coverage now includes membership denial for non-members and cross-business
commerce lists/details, partner histories, inventory, payment and partner
mutations, financial reports, invoices, and receipts. The app health endpoint
and unauthenticated sign-in page returned successfully on port 8001. Browser
login and business switching were not tested.
