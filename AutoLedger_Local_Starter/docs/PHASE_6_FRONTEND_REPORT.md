# AutoLedger Phase 6 Frontend Report

**Status:** Frontend update complete. No database or backend changes were made.
Commerce UI operations remain dependent on the separately approved schema
migration; the current API fails closed when that schema is absent.

## Work completed

- Updated the existing AutoLedger interface to a premium dark navy and charcoal
  theme with blue accents, while preserving the user-selectable light theme.
- Added responsive sidebar routes for Inventory, Suppliers, Customers,
  Purchases, Sales, and Payments alongside the existing vehicle history,
  verification, reports, audit, and team access sections.
- Added searchable supplier and customer tables with Admin-only create/edit
  dialogs connected to the existing APIs. Other currently authorized roles
  can read these directories.
- Added API-backed inventory, purchase, sale, and payment tables, filters,
  PKR valuation/balance display, evidence-backed inventory onboarding, and
  status controls where the API supports them.
- Added purchase/sale forms with multi-vehicle line items, optional initial
  partial/full payment, client-side required-field validation, duplicate
  vehicle checks, double-submit protection, and confirmation prompts. The
  backend remains responsible for authoritative totals and availability.
- Added a payment entry form and filters for payment events.
- Added explicit empty, loading, error, and migration-gate states. A 503 from
  the commerce API is shown as a pending schema requirement, not as an empty
  or successful result.
- Continued using the existing authenticated API client and backend role
  checks. The frontend hides controls by the roles currently present in the
  backend; it does not treat the current `Owner/Viewer` role as a business
  owner role or grant permissions the API does not provide.
- Kept reports tied to existing APIs: vehicle CSV export, vehicle history
  print/PDF, and existing maintenance analytics. No sample statistics or
  business records were added.

## Current route coverage and availability

| UI section | API source | Current limitation |
|---|---|---|
| Dashboard | `/api/dashboard` | Existing vehicle/history metrics only; the API does not supply purchase/sales revenue KPIs. |
| Vehicles and history | `/api/vehicles`, `/api/vehicles/{id}/history` | Existing routes preserved. |
| Suppliers | `/api/suppliers` | Create/update are Admin-only per existing backend policy; no archive endpoint exists. |
| Customers | `/api/customers` | Create/update are Admin-only per existing backend policy; a customer transaction-history endpoint does not exist. |
| Inventory | `/api/inventory` | Returns 503 until the proposed schema is installed with separate approval. |
| Purchases | `/api/purchases` | Returns 503 until the proposed schema is installed with separate approval. |
| Sales | `/api/sales` | Returns 503 until the proposed schema is installed with separate approval. |
| Payments | `/api/payments` | Returns 503 until the proposed schema is installed with separate approval; refunds are not implemented. |
| Reports | `/api/reports/vehicles.csv`, `/api/reports/vehicles/{id}.pdf`, `/api/dashboard` | No purchase, sales, customer, supplier, or payment reporting/export API exists. |
| Audit and team access | Existing audit and auth APIs | Remains Admin-only. |

The commerce list APIs currently return unpaginated results. Frontend search
filters purchase, sale, and payment rows already returned by the API; inventory
search and status filtering are passed to the backend. Supplier/customer
search is server-backed.

## Roles and authorization

- Navigation and action controls reflect the existing backend roles:
  Admin, Dealer, Inspector, and Owner/Viewer.
- Supplier/customer editing is shown only to Admin, matching the existing API.
- Purchase, sale, payment, and inventory management controls are shown only
  to Admin and Dealer; read-only data can be viewed by the currently authorized
  read roles.
- The database and authentication design still use `Owner/Viewer`, not the
  proposed business-owner role. Changing role definitions or permissions is
  outside Phase 6.
- Frontend visibility is only a usability layer; all requests continue to be
  authorized by the backend.

## Validation and testing

- Updated JavaScript was loaded by the local FastAPI static app and parsed by
  the integrated Chromium runtime.
- The local app root returned HTTP 200; `/api/health` and
  `/api/auth/status` returned HTTP 200 from PowerShell.
- A browser-authenticated dashboard/module walkthrough was not completed:
  no real login credentials were used, and the browser session did not finish
  authentication. No user actions were submitted to the live API.
- `node --check` could not run because Node.js is not installed in the
  environment. Browser parsing confirmed JavaScript syntax, but it does not
  replace full browser interaction tests.
- No dedicated frontend automated test runner is present.
- Existing backend regression tests were rerun against the isolated Phase 5
  test database: **22 passed, 4 skipped**. The four skipped tests require the
  proposed commerce schema and triggers, which were not installed.
- `git diff --check` passed.

## Verification follow-up

The subsequent manual verification found and fixed an out-of-scope `event`
reference in the supplier/commerce search handlers and normalized the
`role_name` response from `/api/auth/me` for frontend role checks. Follow-up
browser and live read-only API results, including the migration-gated commerce
endpoints, are recorded in
[PHASE_6_VERIFICATION_REPORT.md](./PHASE_6_VERIFICATION_REPORT.md).

## Known limitations and remaining work

1. Purchase, sale, inventory, and payment screens cannot display or submit
   business data until the separately approved migration has been reviewed and
   applied to an isolated database, then separately approved for live use.
2. The current backend provides no supplier archive/deactivation operation,
   customer transaction-history endpoint, customer/supplier reports, or
   purchase/sales/payment CSV/PDF exports.
3. Dashboard revenue and monthly purchase/sales trends are not shown because
   no current backend endpoint supplies those figures. Displaying estimates
   would risk presenting fabricated metrics.
4. The current account role is `Owner/Viewer`; this phase did not grant
   business-owner management permissions or alter role definitions.
5. Refunds, payment-provider idempotency, and backend transaction integration
   tests remain unavailable as documented in the Phase 5 report.
6. User sign-in and the new UI interactions should be manually verified in a
   local browser using an authorized account before relying on them.

## Subsequent integration update

Later backend integration added a financial summary panel, transaction invoice
and payment receipt download actions, partner activation/history support, and
an access-pending screen for Verification User. These additions do not change
the Phase 6 scope above. Financial and commerce screens still show a clear
migration gate against the current live database; the later API coverage and
test results are documented in
[PHASE_7_BACKEND_REPORT.md](./PHASE_7_BACKEND_REPORT.md),
[PHASE_8_TEST_REPORT.md](./PHASE_8_TEST_REPORT.md), and
[API_REFERENCE.md](./API_REFERENCE.md).

## Files changed in Phase 6

- Updated `frontend/index.html`.
- Updated `frontend/app.js`.
- Updated `frontend/style.css`.
- Added `docs/PHASE_6_FRONTEND_REPORT.md`.

No backend code, `.env`, SQL draft, or database object/record was changed in
this phase. No migration, seed script, deployment, commit, or push was run.
