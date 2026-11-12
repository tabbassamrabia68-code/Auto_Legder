# AutoLedger Final Project Audit

**Audit date:** 2026-11-09  
**Scope:** Existing workspace and application, using source/documentation
inspection, a read-only catalog query against `autoledger_db`, and a separate
read-only connection check of `autoledger_dev_clone`. Tests later wrote only
to the explicitly authorized development clone; no `autoledger_db` writes,
migrations, seeds, or deployment were performed.

## Executive summary

AutoLedger is a working FastAPI/PostgreSQL vehicle-history application with a
responsive HTML/CSS/JavaScript client and substantial proposed dealership
workflow code. It is **not yet a complete dealership application and is not
safe for production shared multi-business use**. The original
`autoledger_db` remains on the legacy schema and roles. The configured local
`.env` now points at `autoledger_dev_clone`, where Phase 4/7 tables were
verified and commerce membership filtering has been implemented/tested.

The latest full regression suite passed 31 tests against the configured
development clone. Results and exact test target are in
[TESTING_REPORT.md](./TESTING_REPORT.md).
These tests do not establish production-grade tenant isolation.

## Original database snapshot: `autoledger_db`

The inspection transaction was set read-only and rolled back after catalog
and row-count queries. Credentials and user personal data were not selected
or reported. This original database was not changed.

- Database: `autoledger_db`
- Server: PostgreSQL 18.6
- Configured port: `2005`
- Public schema: 16 base tables, 95 columns, 16 primary keys, 14 foreign keys,
  5 unique constraints, 14 check constraints, 46 indexes, 4 views, and 13
  named non-internal triggers.
- Current table rows: `audit_logs` 316, `customers` 2, `documents` 78,
  `inspections` 40, `mileage_records` 116, `owners` 39,
  `ownership_records` 41, `purchases` 0, `repair_records` 38, `roles` 5,
  `sales` 0, `service_records` 97, `suppliers` 2, `users` 7, `vehicles` 41,
  `verification_records` 40.
- Live role names: `Admin`, `Dealer`, `Inspector`, `Owner/Viewer`, and
  `Verification User`.
- The live database does **not** contain `businesses`,
  `business_memberships`, `vehicle_inventory`, `purchase_items`, `sale_items`,
  or `payments`.
- Existing purchase and sale headers have no vehicle line-item relationships.
  Do not infer acquisition or sale history from ownership history.

These are a fresh snapshot for this audit. They supersede older counts only
for this date; consult [DATABASE_ARCHITECTURE.md](./DATABASE_ARCHITECTURE.md)
for the prior detailed column and relationship inventory.

## Development clone and current local target

On 2026-11-09 the user confirmed Phase 4/7 migrations had already been
applied to `autoledger_dev_clone`. A read-only connection verified that exact
database on PostgreSQL 18.6 port 2005 and confirmed the membership,
inventory, purchase-item, sale-item, and payment tables exist. The workspace
`.env` now targets this clone. Automated tests are deliberately allowed on
this exact local database only with an explicit opt-in; the live
`autoledger_db` name is blocked by the test guard.

## Implemented and verified

| Area | Actual state |
|---|---|
| Vehicle registry and history | Existing vehicle, owner, ownership, service, repair, mileage, inspection, document, verification, search, history, dashboard, CSV/PDF, and transfer routes exist. Existing feature regression tests are included. |
| Authentication | Password hashing, login, one-time Admin bootstrap, access tokens, optional schema-gated refresh tokens, profile/password update, and logout are implemented. |
| Authorization | Backend permission dependencies and code-defined ceilings exist for seven intended roles. Frontend navigation/control visibility follows `/api/auth/me` permissions but is not a security boundary. |
| Shared records | The approved rule is platform-admin-only writes for globally shared vehicle identity, owners/ownership, and history; business roles are read-only. Backend dependencies and role ceilings enforce this, and isolated auth tests cover it. |
| Legacy roles | Existing role rows and user assignments are not rewritten. Legacy roles receive no effective business permissions in the current policy; a reviewed migration and user-by-user reassignment are still required for continued access. |
| Commerce application code | Supplier/customer, inventory, purchase, sale, payment, invoice, and financial-report route implementations and schemas exist. Commerce schema checks fail closed when required tables/columns are absent. |
| Transaction safety | The proposed-schema integration suite exercises purchase/sale atomicity, inventory locking, duplicate-sale denial, payments, idempotency, and rollback on the isolated test clone. |
| Frontend | Existing single-page HTML/CSS/JavaScript client includes vehicle/history screens and migration-aware commerce views, responsive navigation, theme switching, form feedback, and loading/error states. Viewer UI smoke checks were reported. |
| Audit | Existing audit table and triggers cover legacy record types. Application code also records commerce audit events when its schema is available. |
| Business context | Commerce routes now resolve the selected `X-Business-ID` against an active membership and use the membership's role permissions. The frontend lists/selects memberships and sends the selected header. |
| Commerce tenancy | Supplier/customer, transaction, inventory, payment, history, PDF, and financial-report SQL filters are scoped to the selected business. Cross-business access is tested on the authorized dev clone. |
| Tests | See the latest full result and exact database target in [TESTING_REPORT.md](./TESTING_REPORT.md). The clone accumulates test data and is not a clean fixture. |

## Partially implemented

- **Seven-role catalog:** Current code supports Super Admin, Admin, Business
  Owner, Manager, Accountant, Staff, and Viewer. The live catalog has only
  five legacy roles, so seven-role assignment, registration, and permission
  management cannot work there until a separately reviewed migration is
  approved.
- **Commerce modules:** The original database lacks the required Phase 4/7
  commerce extensions and remains migration-gated. Some legacy partner and
  transaction headers exist, but new commerce workflows require the
  line-item, inventory, payment, and business-membership schema present only
  on the development clone.
- **Business roles:** Commerce requests validate active membership and use
  the membership role. Business creation/member administration, audit trigger
  propagation, and broader endpoint coverage remain incomplete.
- **Dashboard/reporting:** Existing dashboard and reports provide vehicle
  history and maintenance metrics. Dealership-level live KPIs, date-filtered
  business reports, and tenant-scoped exports are not implemented against the
  live schema.
- **Record lifecycle:** Supplier/customer active flags are proposed-schema
  dependent. Vehicle archival and reversible financial cancellation/refund
  workflows are not complete.
- **Frontend workflows:** Some forms/buttons render based on permissions and
  schemas available in the isolated clone; no complete live end-to-end
  dealership workflow can pass against the current database.

## Missing or blocked requirements

1. **Multi-business security:** Commerce API membership resolution and
   business filters now exist, with cross-business tests on the dev clone.
   Business/member administration, complete trigger/audit tenant handling,
   broader role and endpoint coverage, and a fresh-clone verification remain.
   Shared multi-tenant production deployment is blocked.
2. **Vehicle identity workflow:** The policy is now clarified: only Super
   Admin can create/correct globally shared vehicle identity and approved
   history; a business-user submission/review request workflow for an unknown
   VIN is not implemented.
3. **Live schema enablement:** Required Phase 4/7 SQL is draft-only. No schema
   migration history/version runner is established for approved upgrades.
4. **Legacy access:** The five live roles do not match the seven active role
   set. No blanket reassignment was or should be made. A reviewed per-user
   mapping and an auditable Super Admin provisioning procedure are outstanding.
5. **Inventory attributes:** Existing `vehicles` lacks mileage, acquisition
   price, asking/sale price, supplier, tenant ownership, archive state, images,
   and updated timestamp. Some information is intended for normalized
   inventory/transaction/document relations, but no image upload/storage
   service exists.
6. **Documents and inspection files:** Structured document/inspection
   records exist; secure upload, malware/type/size validation, storage
   isolation, and file authorization are not implemented.
7. **Archival/history:** Physical vehicle deletion is constrained by linked
   history, but there is no vehicle archive flow. Supplier/customer
   deactivation is migration-dependent. Posted transaction reversal/refund
   support is not complete.
8. **Operational production controls:** Production TLS, proxy configuration,
   managed secrets, backup monitoring, restore drill, MFA/rate limiting,
   password recovery, and deployment have not been verified.

## Database and migration findings

- Existing tables preserve the vehicle-history purpose and have primary and
  foreign keys, checks, indexes, views, and triggers.
- `purchases` and `sales` are currently empty headers, with nullable
  supplier/customer references and nullable totals. Their existing definitions
  do not satisfy the proposed multi-line transaction model.
- `db/proposed_phase4/` and `db/proposed_phase7/` are applied to the
  development clone only. `002_business_membership_design.sql` remains a
  foundation draft, not deployable alone. Historical business rows remain
  unassigned.
- Before using the tenant draft, review composite tenant foreign keys,
  same-tenant trigger behavior, treatment of unassigned records, transaction
  ownership across businesses, and the globally shared vehicle identity
  workflow on an isolated PostgreSQL 18 restore.
- Never run `db/reset_and_reseed.ps1` as a migration runner on the live
  database. Existing SQL scripts include data-changing seed/refresh behavior.

## Frontend and backend findings

- The frontend is served by FastAPI and uses same-origin API calls; it is not a
  separately deployed SPA.
- Permission-based navigation is a usability feature. Every protected API
  must independently authorize the caller.
- Global user administration and the unscoped legacy audit trail are restricted
  to Super Admin until membership-scoped endpoints exist. The Admin role must
  not use these global routes as business-level administration.
- Existing generic ledger endpoints are suitable for existing history
  resources but do not provide business-scoped ownership automatically.
- Commerce endpoints use active membership context and tenant-filtered
  queries. Shared vehicle/history search, reports, and dashboards remain
  global by design; business membership CRUD, tenant-aware database triggers,
  and scoped audit views still need implementation/review.
- README role/module statements predate the final role-policy work and need
  alignment. Production instructions correctly require migration approval and
  external secrets but the container image has not been built.

## Test coverage and gaps

The latest test run is documented in [TESTING_REPORT.md](./TESTING_REPORT.md).
The expanded suite covers authentication, role guards, existing
vehicle-history regression, partner CRUD/audit, commerce transactions,
concurrent sale prevention, and cross-business denial on the development
clone. Tests do **not** currently establish:

- Business/member administration, revocation, or browser-level switching.
- Tenant-aware database trigger/audit behavior or isolation of global
  shared-history endpoints (which are intentionally shared/read-only).
- Unknown-VIN registration authority or shared-history policy.
- Live migration compatibility or a production restore/rollback drill.
- Secure file uploads.

## Remaining phases

1. **Audit and policy closure:** Resolve the global vehicle-identity creation
   rule and review the current seven-role permission matrix against the
   business/tenant model.
2. **Migration engineering:** Review and version the additive migrations;
   apply only to a disposable isolated restore for compatibility tests.
3. **Tenant enforcement:** Complete membership provisioning, tenant-aware
   lifecycle/audit triggers, browser switching tests, and expanded
   cross-tenant denial coverage.
4. **Commerce enablement:** Continue workflow verification against the
   migrated development clone, resolve edge cases, and preserve historical
   rows unassigned.
5. **Inventory/document lifecycle:** Complete vehicle archival, secure media
   storage, and document access controls as approved.
6. **UI/report completion:** Add business-scoped KPIs and audit views,
   pagination where needed, and verified action handling.
7. **Release readiness:** Rehearse restore/rollback and complete security,
   configuration, local setup, and browser regression checks.
8. **Production changes:** Require a fresh verified backup and separate
   explicit approval before applying any live database migration or
   deployment.

## Final status

The project is an advanced local vehicle-history application with proposed
dealership extensions, not yet a complete or tenant-safe dealership platform.
The seven-role application policy is implemented in the current code, but the
live database is still on the legacy five-role schema. Live database records
and schema were not changed during this audit.
