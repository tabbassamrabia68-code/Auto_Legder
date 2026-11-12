# AutoLedger Role and Tenant Readiness

## Status

The backend and frontend use a centralized permission policy for the approved
role names. The local app configuration now targets `autoledger_dev_clone`
on PostgreSQL port 2005, where the proposed Phase 4/7 schema was verified.
The original `autoledger_db` was not changed. No tenant backfill or legacy
user reassignment was performed.

The active roles are:

| Role | Intended scope |
|---|---|
| Super Admin | System-wide administration |
| Admin | Full business-management permissions |
| Business Owner | Business management and financial oversight |
| Manager | Operational management |
| Accountant | Financial and transaction records |
| Staff | Limited vehicle/history/verification operations |
| Viewer | Read-only vehicle and history access |

`backend/security.py` defines each role's permission ceiling. Persisted
`role_permissions` can narrow those permissions but cannot expand them.
Super Admin has the explicit wildcard policy. Route authorization is checked
on the server; frontend visibility is only a usability layer, not a security
boundary.

The shared vehicle identity, owner/ownership, and approved vehicle-history
records are read-only to business roles. Only Super Admin may create, correct,
transfer, or delete those globally shared records. This is enforced by
dedicated backend dependencies and by withholding the corresponding
management permissions from all other active role ceilings. Business
inventory and transaction items remain separate business data.

Global user administration and the unscoped audit trail remain restricted to
Super Admin. Business membership administration remains a required follow-up,
not a claimed feature.

## Legacy role handling

The legacy role labels `Dealer`, `Inspector`, `Owner/Viewer`, and
`Verification User` remain in the database with their existing user
assignments. The application does not grant those roles business permissions
and does not permit new assignments to them. No existing records or users are
deleted or silently rewritten.

The following are mapping candidates only, not automatic conversions:

| Existing role | Candidate for a user-by-user review | Reason for review |
|---|---|---|
| Dealer | Manager or Staff | Old dealer grants and new operational duties do not align exactly; Manager may grant additional customer, supplier, and history access. |
| Inspector | Staff or Viewer | The correct choice depends on whether the person performs inspections or only reads vehicle history. |
| Owner/Viewer | Viewer | The label suggests read-only access, but account identity and intended business membership still need confirmation. |
| Verification User | No default mapping | Access stays blocked until an administrator explicitly assigns a reviewed active role. |

Before any mapping, export the legacy user list for an authorized review,
record each approved user/role/business assignment, provision the Super Admin
through an auditable process, and verify that an active administrator remains.
Do not use a blanket SQL `UPDATE` based only on the old role name.

## Tenant boundary design

The approved deployment model is shared multi-tenancy: a user may belong to
multiple businesses; vehicle identity and vehicle history remain shared and
read-only where permitted; inventory, suppliers, customers, purchases, sales,
payments, reports, and business audit records are private to a business.
Existing records remain unassigned until an explicit mapping is approved.
Role is intended to be assigned per business membership.

`db/proposed_phase7/002_business_membership_design.sql` remains a proposed
foundation for businesses, memberships, nullable tenant keys, and composite
tenant foreign keys. It has been applied by the user to the development clone,
not to `autoledger_db`. Current application changes resolve the selected
business membership on commerce API requests and scope commerce reads,
writes, reports, payments, and generated PDFs. The current application still
does not:

- Create businesses or manage/assign/revoke memberships through a
  tenant-authorized administration workflow.
- Carry and verify tenant context through all pre-existing database lifecycle
  and audit triggers.
- Expose a business-scoped audit UI/API; unscoped global audit remains
  Super-Admin-only.
- Verify multi-business switching end-to-end in a browser and with all roles.
- Apply a reviewed mapping to historical customers, suppliers, commerce
  records, inventory, or audit rows.

The frontend now selects among existing active memberships and sends
`X-Business-ID`; the backend tests verify commerce cross-business denial on
the development clone. Until the remaining items and broader testing are
complete, do not deploy this as a shared multi-tenant service. The role policy
alone cannot prevent cross-business access through endpoints or database
triggers not covered by the commerce filters.

## Safe implementation sequence

1. Review the Phase 4/7 drafts against a fresh PostgreSQL 18 restore.
2. Approve an explicit policy for unassigned legacy records and the
   user-by-user legacy-role mapping.
3. Implement business/member provisioning and tenant-aware audit/lifecycle
   triggers on the development clone.
4. Test business switching, cross-tenant denial, concurrent sales,
   unassigned-row behavior, and rollback on a fresh isolated database.
6. Only after independent review and a fresh verified backup, request separate
   approval for production migrations and data mapping.
7. Keep production deployment blocked until all tenant-scoped tests pass.

## Verification state

The latest isolated backend suite and cross-business test results are
documented in [TESTING_REPORT.md](./TESTING_REPORT.md). Earlier browser checks
confirmed Viewer navigation, responsive menu, and theme switching. Tenant
selection now exists in the frontend but browser-level switching has not yet
been verified. `autoledger_db` was not changed; `.env` now points at the
development clone.
