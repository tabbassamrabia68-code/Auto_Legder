# AutoLedger Phase 6 Verification Report

## Verification scope

This report covers manual Phase 6 frontend verification only. The application
was run locally at `http://127.0.0.1:8001` using the existing project virtual
environment and configuration. Database connection settings remained
`localhost:2005` and `autoledger_db`; credentials are intentionally omitted.

The browser UI walkthrough used test-only mocked API responses. Separately,
read-only authenticated API requests were sent to the running application.
No business create, update, or delete operation was submitted.

## Results

| Feature | Result | Evidence and limits |
|---|---|---|
| Sign in | Partially verified | Invalid credentials were rejected with HTTP 401. The successful sign-in flow was exercised with mocked UI responses only; a real account/password was not supplied or tested. |
| Sign out | Passed in browser walkthrough | The mocked signed-in UI returned to the sign-in screen and cleared the test session. No real user session was used. |
| Dashboard | Passed | Dashboard rendered in the browser walkthrough; authenticated live `GET /api/dashboard` returned HTTP 200. |
| Vehicle search | Passed | Search and filtered vehicle table rendered using mocked UI data; live authenticated `GET /api/vehicles` returned HTTP 200. |
| Vehicle history | Passed | History view rendered in the browser walkthrough; live authenticated vehicle-history GET returned HTTP 200. |
| Owners | Passed | Owners view rendered; live authenticated owners GET returned HTTP 200. |
| Customers | Passed for existing read/UI flow | Customer page, empty state, and form rendered with test-only UI responses; live authenticated customer list GET returned HTTP 200. No customer was created or updated. |
| Suppliers | Passed for existing read/UI flow | Supplier page, empty state, and form rendered with test-only UI responses; live authenticated supplier list GET returned HTTP 200. No supplier was created or updated. |
| Inventory | Blocked by unapplied schema | The migration gate rendered in the browser. Live authenticated `GET /api/inventory` returned HTTP 503 because the proposed commerce schema is absent. |
| Purchases | Blocked by unapplied schema | The migration gate rendered in the browser. Live authenticated `GET /api/purchases` returned HTTP 503. No purchase was submitted. |
| Sales | Blocked by unapplied schema | The migration gate rendered in the browser. Live authenticated `GET /api/sales` returned HTTP 503. No sale was submitted. |
| Payments | Blocked by unapplied schema | The migration gate rendered in the browser. Live authenticated `GET /api/payments` returned HTTP 503. No payment was submitted. |
| Dark/light theme | Passed | Theme toggle changed the browser UI between the two themes. |
| Responsive mobile navigation | Passed | The navigation opened, routed to a selected section, and closed as expected at the tested mobile viewport. |
| Existing reports | Passed for read/export endpoints | Authenticated vehicle CSV GET returned HTTP 200; dashboard and vehicle-history GETs also returned HTTP 200. |
| Existing vehicle functionality | Passed for read-only coverage | Authenticated vehicle list, history, dashboard, and export requests succeeded. CRUD mutation paths were not exercised to avoid changing live records. |

## Findings and fixes

The manual walkthrough exposed a JavaScript integration defect: the supplier
and commerce search handlers were in the shared API helper, where successful
requests could reference an out-of-scope `event`. The handlers were moved into
the document input listener. A separate response-shape mismatch was corrected
by normalizing the existing `/api/auth/me` `role_name` field to the frontend's
`role` property. The search, auth initialization, and navigation walkthrough
then rendered and operated without that runtime error.

The server root, `/api/health`, and `/api/auth/status` returned HTTP 200.
Authenticated read-only requests for profile, dashboard, vehicles, owners,
customers, suppliers, CSV export, and vehicle history returned HTTP 200. The
invalid login returned HTTP 401. Inventory, purchases, sales, and payments
returned HTTP 503 as designed while their schema remains unapplied.

No screenshots were saved. Browser snapshots and the HTTP responses above
were the available verification evidence. UI data used in mocked walkthroughs
(including the test vehicle/user) was not written to the project or database.

## Automated test status

The existing Phase 6 implementation report records the isolated backend
regression result as **22 passed, 4 skipped**; the skipped cases require the
proposed commerce schema. A rerun during this verification stopped safely
before test collection because `AUTOLEDGER_TEST_DB_NAME` was not configured.
`tests/conftest.py` requires a dedicated `autoledger_test_` database name and
refuses to use the live database. No test database was guessed, created, or
modified.

`git diff --check` completed without whitespace errors. Git reported existing
LF/CRLF conversion warnings for several already changed files.

## Remaining issues

- Successful authentication with a real authorized account was not verified;
  no real credentials were supplied.
- Supplier/customer form submissions and all commerce mutations were not
  tested. The commerce endpoints remain unavailable until the proposed schema
  migration is separately approved and applied.
- The current automated test run requires an explicitly configured isolated
  test database before it can run.
- The workspace-level `start.ps1` expects a `.venv` at the workspace root,
  which is absent. The application was instead started with the existing
  project-level `.venv` used by `Start_AutoLedger.bat`.

## Database and Git safety

No migration or seed script was executed. No database DDL or business-data
write was issued; live application checks were read-only GET requests plus an
invalid login attempt. No database records or schema were changed by this
verification. Existing staged and unstaged Git changes were preserved; no
commit, push, reset, clean, or discard was performed.

## Exact next recommended step

After review and separate approval, configure a dedicated isolated
`autoledger_test_` database and validate the proposed commerce migration there.
Then obtain separate approval before any live migration. Do not treat
inventory, purchase, sale, or payment workflows as operational before that
schema is validated and installed. This report does not start Phase 7.
