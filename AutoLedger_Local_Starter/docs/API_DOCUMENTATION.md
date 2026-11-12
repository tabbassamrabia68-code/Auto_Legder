# AutoLedger API Documentation

The detailed route/method/access reference is maintained in
[API_REFERENCE.md](./API_REFERENCE.md). FastAPI generates the authoritative
OpenAPI schema from route definitions at `/openapi.json`; interactive Swagger
UI is served at `/docs` while the local application is running.

## API groups

- Authentication/account: `/api/auth/*`
- Existing vehicle registry and shared history: `/api/vehicles/*`,
  `/api/records/*`
- Dashboard/search: `/api/dashboard`, `/api/search`
- Legacy vehicle reports: `/api/reports/vehicles.csv` and vehicle-history
  PDF
- Proposed dealership operations: `/api/suppliers`, `/api/customers`,
  `/api/purchases`, `/api/sales`, `/api/inventory`, `/api/payments`, and
  financial reporting/PDF routes

## Authentication and errors

Protected endpoints use a bearer access token, with optional HttpOnly refresh
cookie support only after its proposed authentication schema is installed.
`GET /api/auth/businesses` lists active memberships and effective role
permissions. The client selects a business and sends its ID using
`X-Business-ID`. Each business API request resolves the effective role from
that user's active membership; the global user role does not authorize
business data.
Common responses are `401` unauthenticated, `403` unauthorized, `404` not
found, `409` duplicate/conflicting state, `422` invalid input, and `503` for
database/schema readiness failures.

Database credentials, password hashes, bearer tokens, refresh tokens, and raw
SQL errors must not be returned or copied into client-facing error messages.

## Availability caveat

`autoledger_db` remains on the legacy schema and is not the currently
configured app target. The configured local `.env` now points at
`autoledger_dev_clone`, where Phase 4/7 schema is installed. Commerce routes
remain schema-gated if the required relations are absent.

Commerce endpoints require active membership and filter suppliers,
customers, purchases, purchase items, sales, sale items, inventory, payments,
PDFs, financial reports, and commerce audit writes to the selected business.
Isolated cross-business tests cover listing, detail, update, histories,
invoice/receipt, inventory, payments, and financial reports. Business/member
provisioning and tenant-aware database triggers are still incomplete; these
application filters alone do not establish production-grade tenant
isolation.

Business roles may read shared vehicle/history records. Only Super Admin may
mutate globally shared vehicle identity, owners, ownership, or history. Global
user management and unscoped audit routes are Super Admin-only until
business-scoped management is implemented.
