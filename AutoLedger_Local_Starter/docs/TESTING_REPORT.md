# AutoLedger Testing Report

## Database target and safeguards

The backend integration suite was run against `autoledger_dev_clone` on the
local PostgreSQL instance at port 2005. It contains the Phase 4/7 schema and
test-generated rows, so it is not a clean fixture. Tests required the explicit
`AUTOLEDGER_ALLOW_DEV_CLONE=1` opt-in and were guarded against `autoledger_db`.
No schema or records in `autoledger_db` were changed.

## Automated results

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

- Python compilation: passed.
- Full backend suite: **31 passed in 110.88 seconds**.
- `git diff --check`: passed; Git emitted line-ending conversion warnings
  for existing files.

## Coverage verified

- Password hashing and authentication flows.
- Seven-role permission ceilings and legacy-role denial.
- Admin denied global user/audit access until tenant-scoped endpoints exist.
- Only Super Admin may mutate shared vehicle identity and history.
- Existing vehicle search/history/dashboard/report regression.
- Commerce partner CRUD and audit, purchase/sale/payment transactions,
  inventory reservation, concurrent duplicate sale prevention, idempotency,
  balance calculation, and rollback on the isolated migrated clone.
- Request validation and database integrity error handling.
- Business membership resolution, denied non-member requests, and
  cross-business commerce list/detail/history, mutation, report, and PDF
  isolation.

## Browser smoke checks

The app started on `127.0.0.1:8001` using the existing `.env`, which targets
`autoledger_dev_clone`. The health endpoint and sign-in page returned
successfully. No authenticated browser session was available for validating
the business selector; no screenshot was saved. Node.js is unavailable, so
`node --check` could not be run.

## Not verified / blocking tests

- Business membership creation, revocation, and administration are not
  implemented.
- Browser-level membership switching and cross-business isolation for shared
  vehicle/history endpoints, audit, and file access are not verified.
- Database trigger propagation/audit isolation and production-grade RLS are
  not verified.
- Live migration/restore/rollback and live commerce workflows.
- Secure upload and file authorization.
- Production hosting, TLS/proxy, secret manager, monitoring, and recovery.

The clone tests demonstrate application-level commerce filtering only; they
do not prove proposed migrations safe for production or complete tenant
isolation. See [ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md](./ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md).
