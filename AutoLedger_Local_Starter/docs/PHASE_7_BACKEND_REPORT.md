# AutoLedger Phase 7 — Security and Backend Extensions

## Status

Backend authentication, authorization, partner lifecycle, payment safety, and
reporting extensions are implemented in application code. The current worktree
also centralizes route authorization around the approved seven-role policy.
The required SQL is still **PROPOSED — NOT EXECUTED**. The live database has
not been changed, so commerce and migration-dependent endpoints remain gated.

## Implemented

- Added refresh-session issuance, SHA-256 token digests, single-use rotation,
  expiry/revocation checks, password-change revocation, and logout revocation.
- Added profile and password endpoints, input validation, and token-version
  invalidation after password changes.
- Added a Super Admin role distinct from Admin. Admin cannot create or manage
  Super Admin accounts; Super Admin can manage role permission assignments.
- Added code-defined permission ceilings for the seven active roles:
  Super Admin, Admin, Business Owner, Manager, Accountant, Staff, and Viewer.
  Persisted permission rows can restrict a role but cannot expand its
  approved code-defined permissions; Super Admin retains its explicit
  wildcard policy.
- Global vehicle identity, owner/ownership, and history mutation is now
  Super Admin-only. Business roles receive read-only access to those shared
  records; their inventory and commerce operations are distinct business
  data. Global user administration and the unscoped legacy audit trail are
  also restricted to Super Admin until tenant-scoped management APIs exist.
- Preserved legacy roles (Dealer, Inspector, Owner/Viewer, and Verification
  User) without automatic reassignment; they receive no effective business
  permissions. New user creation and role changes accept only the seven
  active role names. A human-reviewed mapping is required before any legacy
  user is reassigned.
- Vehicle/history, record-ledger, commerce, and account-management routes use
  centralized permission checks instead of legacy role-name allowlists.
- The frontend derives page navigation and management controls from effective
  permissions. Profile access remains available to authenticated accounts;
  accounts with no effective business permissions receive an access-pending
  state.
- Added partner activation and transaction-history APIs, guarded by schema
  readiness checks.
- Added payment idempotency-key handling and transaction-scoped advisory
  locking so identical retries resolve to the original payment and conflicting
  retries return `409`.
- Added financial summary and monthly reporting, with PKR and no-tax policy.
  Gross profit is based only on a received purchase cost recorded for the
  vehicle; missing legacy acquisition cost is counted and never estimated.
- Added invoice and payment receipt PDF generation.
- Configured production CORS/trusted-host requirements, security headers,
  database URL support, and TLS-required PostgreSQL connections when
  `APP_ENV=production`.
- Added a clear frontend access-pending state for accounts without effective
  business permissions and fixed a content-security-policy mismatch for the
  configured web fonts.

## API surfaces

Authentication additions include `PATCH /api/auth/me`,
`POST /api/auth/password`, `POST /api/auth/refresh`,
`POST /api/auth/logout`, `GET /api/auth/roles`, and
`PUT /api/auth/roles/{role_id}/permissions`.

Commerce additions include customer/supplier activation and history,
idempotent payment creation, financial reporting, invoice PDFs, and receipt
PDFs. The complete route list is in [API_REFERENCE.md](./API_REFERENCE.md)
and the live OpenAPI document is served at `/openapi.json`.

## Proposed migration

`db/proposed_phase7/001_auth_business_extensions.sql` adds the token version,
refresh-token table, permission catalog and role mappings, partner activation
flags, and payment idempotency key/index. It is a design/implementation draft
only. It depends on the Phase 4 commerce tables and has not been executed
against `autoledger_db`.

The code checks required columns/tables and returns a migration-gated response
instead of assuming the proposed schema is live. Existing records are not
backfilled, relabeled, or converted by the backend.

The proposed role grants in `001_auth_business_extensions.sql` now exclude
legacy roles. Legacy role rows and existing user assignments remain untouched.
`db/proposed_phase7/002_business_membership_design.sql` proposes the tenant
foundation and is explicitly not deployable by itself; backend membership
resolution, tenant-scoped queries, and tenant-aware lifecycle/audit triggers
are still required. See [ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md](./ROLE_AND_TENANCY_IMPLEMENTATION_STATUS.md).

## Validation and known limitations

- The full isolated backend suite passed **29 tests** after the latest
  Super Admin-only shared-record rule; supplemental browser checks covered
  Viewer navigation, responsive menu behavior, and theme switching. Details are in
  [PHASE_8_TEST_REPORT.md](./PHASE_8_TEST_REPORT.md).
- The production database has no installed Phase 4/7 extensions at the time
  this report was prepared. Purchase, sale, inventory, payment, partner
  activation, financial report, refresh, permission-catalog workflows, and
  public Viewer registration cannot be treated as operational there until a
  separately approved migration is reviewed and applied. Viewer registration
  fails closed with `503` if the approved Viewer role is not installed.
- No initial Super Admin is automatically assigned. Provisioning that
  account needs a reviewed, auditable procedure after migration approval.
- There is no payment-provider integration, refund API, tax calculation, or
  automated conversion from customer to owner.
- Permission-catalog and role-permission administration remain migration
  gated. Role permission edits are bounded by the code-defined role ceilings;
  they cannot elevate a role beyond its approved permissions. Legacy users
  are not automatically mapped or reassigned.
- Business Admins do not yet have membership-scoped user/audit administration;
  those global endpoints are intentionally not exposed to them.
- The existing schema and implemented queries do not provide businesses,
  memberships, or business-scoped ownership keys. Role authorization is not
  tenant isolation. Business Owner, Manager, Accountant, Staff, and Viewer
  data is not safe for a shared multi-tenant deployment until tenant schema,
  active-membership authorization, and tenant filters are implemented and
  tested across every endpoint and report. Existing records remain unassigned
  until an explicit mapping decision is approved.
- Password reset/recovery, MFA, rate limiting, and external identity
  federation are not implemented.

## Safety

No live schema migration, seed script, deployment, commit, or push was run.
All database integration tests and browser requests ran against the
`autoledger_test_` clone. Existing staged and unstaged changes were preserved.
