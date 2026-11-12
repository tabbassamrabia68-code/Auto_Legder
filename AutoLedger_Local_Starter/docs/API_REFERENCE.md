# AutoLedger API Reference

The FastAPI application publishes the authoritative OpenAPI document at
`/openapi.json` and interactive Swagger UI at `/docs`. Run the app locally to
open `http://127.0.0.1:8001/docs`.

All protected routes require `Authorization: Bearer <access_token>` unless
they use the refresh-session cookie. Request and response models are defined
in `backend/schemas.py`, `backend/commerce_schemas.py`, and `backend/auth.py`.
Database values and credentials must not be copied into support logs.

## Authentication and account management

| Method | Path | Access / notes |
|---|---|---|
| `GET` | `/api/auth/status` | Public setup status. |
| `POST` | `/api/auth/bootstrap` | Public, one-time initialization of the existing Admin account. |
| `POST` | `/api/auth/login` | Public; returns a short-lived access token and, when the proposed auth migration is installed, an HttpOnly refresh cookie. |
| `POST` | `/api/auth/register` | Public read-only Viewer registration. |
| `GET` | `/api/auth/me` | Authenticated current account. |
| `GET` | `/api/auth/businesses` | Authenticated user's active memberships and effective role permissions. |
| `PATCH` | `/api/auth/me` | Authenticated display-name update. |
| `POST` | `/api/auth/password` | Authenticated password change; requires token-version schema. |
| `POST` | `/api/auth/refresh` | Rotates the refresh cookie; returns `503` until its proposed table is installed. |
| `POST` | `/api/auth/logout` | Revokes the refresh cookie when present and clears it. |
| `GET` | `/api/auth/roles` | Super Admin permission required; requires the proposed RBAC schema. |
| `PUT` | `/api/auth/roles/{role_id}/permissions` | Super Admin permission required; replaces that role's permission grants. |
| `GET` | `/api/auth/users` | Super Admin only. This global list is not business-membership scoped. |
| `POST` | `/api/auth/users` | Super Admin only until business-scoped membership management is implemented. |
| `GET` | `/api/auth/users/{user_id}` | Super Admin only. |
| `PATCH` | `/api/auth/users/{user_id}` | Super Admin only, with protection for the final active Super Admin. |

Admin and Super Admin are separate roles. Admin's intended scope is business
administration, but membership-scoped user management is not implemented.
Super Admin is the only role that can use the current global user and role
administration endpoints. The initial Super Admin must be provisioned through
a reviewed administrative procedure after the RBAC migration is separately
approved.

## Vehicles, lifecycle records, and reports

| Method | Path | Access / notes |
|---|---|---|
| `GET` | `/api/health` | Public database health check. |
| `GET` | `/api/dashboard` | Authenticated operational summary. Verification User is denied. |
| `GET` | `/api/search?q=...` | Search vehicles and owners; Verification User is denied. |
| `GET` | `/api/vehicles` | Search/filter and paginate the existing vehicle registry. |
| `POST` | `/api/vehicles` | Super Admin only; creates globally shared vehicle identity. |
| `GET` | `/api/vehicles/{vehicle_id}` | Vehicle detail. |
| `PUT` | `/api/vehicles/{vehicle_id}` | Super Admin only; edits globally shared vehicle identity. |
| `DELETE` | `/api/vehicles/{vehicle_id}` | Super Admin only; database references may prevent deletion. |
| `POST` | `/api/vehicles/{vehicle_id}/transfer` | Super Admin only; records a globally shared ownership transfer. |
| `GET` | `/api/vehicles/{vehicle_id}/history` | Existing ownership, service, repair, mileage, inspection, document, and verification history. |
| `GET` | `/api/records/{resource}` | Paginated existing ledger sections; unscoped audit is Super Admin-only. |
| `GET` | `/api/records/{resource}/{record_id}` | Single ledger record; unscoped audit is Super Admin-only. |
| `POST` | `/api/records/{resource}` | Super Admin only; these are globally shared history records. |
| `PATCH` | `/api/records/{resource}/{record_id}` | Super Admin only; these are globally shared history records. |
| `DELETE` | `/api/records/{resource}/{record_id}` | Super Admin only; immutable history is not directly deletable. |
| `GET` | `/api/reports/vehicles.csv` | Operational vehicle export. |
| `GET` | `/api/reports/vehicles/{vehicle_id}.pdf` | Printable vehicle history. |

## Business partners and commerce

These endpoints depend on the Phase 4/7 schema. It is installed only on the
local `autoledger_dev_clone`; the original `autoledger_db` has not been
migrated. On a database missing required tables, columns, or triggers,
commerce endpoints return an explicit `503` migration gate. No `503` response
should be interpreted as an empty successful result.

| Method | Path | Access / notes |
|---|---|---|
| `GET` | `/api/suppliers` | Authorized read roles; supports search and inactive filtering. |
| `POST` | `/api/suppliers` | Admin, Super Admin, Business Owner, or Manager. |
| `GET` | `/api/suppliers/{supplier_id}` | Authorized read roles. |
| `GET` | `/api/suppliers/{supplier_id}/purchases` | Authorized read roles; commerce schema required. |
| `PATCH` | `/api/suppliers/{supplier_id}` | Partner managers. |
| `PATCH` | `/api/suppliers/{supplier_id}/active` | Partner managers; Phase 7 schema required. |
| `GET` | `/api/customers` | Authorized read roles; supports search and inactive filtering. |
| `POST` | `/api/customers` | Admin, Super Admin, Business Owner, or Manager. |
| `GET` | `/api/customers/{customer_id}` | Authorized read roles. |
| `GET` | `/api/customers/{customer_id}/sales` | Authorized read roles; commerce schema required. |
| `PATCH` | `/api/customers/{customer_id}` | Partner managers. |
| `PATCH` | `/api/customers/{customer_id}/active` | Partner managers; Phase 7 schema required. |
| `GET` | `/api/purchases` and `/api/purchases/{purchase_id}` | Authorized read roles; commerce schema required. |
| `POST` | `/api/purchases` | Business transaction managers; commerce schema required. |
| `GET` | `/api/sales` and `/api/sales/{sale_id}` | Authorized read roles; commerce schema required. |
| `POST` | `/api/sales` | Business transaction managers; commerce schema required. |
| `GET` | `/api/inventory` and `/api/inventory/{vehicle_id}` | Authorized read roles; commerce schema required. |
| `POST` | `/api/inventory/{vehicle_id}` | Inventory managers. |
| `PATCH` | `/api/inventory/{vehicle_id}` | Inventory managers; constrained status transitions only. |
| `GET` | `/api/payments` and `/api/payments/{payment_id}` | Authorized read roles; commerce schema required. |
| `POST` | `/api/payments` | Business Owner, Admin, or Accountant permission; supports idempotency keys when migration is installed. |
| `PATCH` | `/api/payments/{payment_id}` | Payment managers. |
| `GET` | `/api/sales/{sale_id}/invoice.pdf` | Authorized financial-read roles; completed sale required. |
| `GET` | `/api/payments/{payment_id}/receipt.pdf` | Authorized financial-read roles; completed payment required. |
| `GET` | `/api/reports/financial` | Authorized financial-read roles; commerce schema required. |

All new business operations use parameterized SQL and require `X-Business-ID`
for an active membership. Commerce reads and writes are scoped to that
business. Purchase and sale writes
run transactionally; sale creation locks inventory in stable vehicle-ID
order. A unique sale item plus inventory status and workflow triggers prevent
concurrent duplicate sale of a currently stocked vehicle. Customers are never
automatically converted to owners, and commerce sales do not rewrite the
separate ownership ledger.

**Tenant limitation:** membership resolution and commerce query filters have
cross-business API tests on the development clone. Business/member
administration, tenant-aware lifecycle/audit triggers, browser switching
verification, and coverage of shared vehicle/history, audit, and file APIs
remain incomplete. Do not treat this as production-ready multi-tenancy.

## Error behavior

Common statuses are `401` for missing/invalid authentication, `403` for
unauthorized roles, `404` for missing resources, `409` for duplicate or
conflicting state, `422` for request/constraint validation, and `503` for an
unavailable database or an unapplied proposed schema. Database error details
are logged server-side; HTTP responses avoid returning credentials or raw SQL.
