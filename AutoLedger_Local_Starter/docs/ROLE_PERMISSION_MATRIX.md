# AutoLedger Role and Permission Matrix

This matrix describes the **current application-code policy** in
`backend/security.py`. It does not claim that these roles are installed in the
live database. The live catalog still contains `Admin`, `Dealer`, `Inspector`,
`Owner/Viewer`, and `Verification User`; the proposed seven-role migration is
not executed.

| Permission area | Super Admin | Admin | Business Owner | Manager | Accountant | Staff | Viewer |
|---|---:|---:|---:|---:|---:|---:|---:|
| Platform settings / full system permissions | Yes | No | No | No | No | No | No |
| Global role catalog / role-grant administration | Yes | No | No | No | No | No | No |
| Global user account administration | Yes | No* | No* | No | No | No | No |
| Unscoped audit trail | Yes | No* | No | No | No | No | No |
| Read shared vehicles and history | Yes | Yes | Yes | Yes | No | Yes | Yes |
| Create/correct/delete shared vehicle identity | Yes | No | No | No | No | No | No |
| Change shared owners/ownership/history | Yes | No | No | No | No | No | No |
| Read/manage customers and suppliers | Yes | Read/manage* | Read/manage* | Read/manage* | Read | No | No |
| Read/manage inventory | Yes | Read/manage* | Read/manage* | Read/manage* | No | No | No |
| Read/manage purchases and sales | Yes | Read/manage* | Read/manage* | Read/manage* | Read | No | No |
| Read/manage payment events | Yes | Read/manage* | Read/manage* | Read only | Read/manage | No | No |
| Financial reports and invoices | Yes | Yes | Yes | No | Yes | No | No |
| Operational reports | Yes | Yes | Yes | Yes | No | No | No |
| Profile and password | Authenticated account | Authenticated account | Authenticated account | Authenticated account | Authenticated account | Authenticated account | Authenticated account |

`*` These permissions apply to the active business only on commerce endpoints
that require `X-Business-ID` and resolve an active membership. Membership
selection and filtering are implemented for the current commerce API surface;
business/member administration and tenant-aware database triggers are not
complete, so this is not yet a production-ready shared multi-business system.

## Enforcement notes

- Backend dependencies are authoritative; hiding a page or button is not
  authorization.
- Only Super Admin may mutate globally shared vehicle identity, owners,
  ownership transfers, and approved vehicle-history records. This is enforced
  using a dedicated backend dependency and tested through API integration.
- Admin does not receive global `users.manage` or `audit.read`. Those APIs
  return `403` for Admin until business-scoped membership and audit endpoints
  exist.
- For active non-Super-Admin roles, effective permissions are intersected
  with the code-defined ceiling. Persisted role grants cannot expand that
  ceiling. Super Admin uses the explicit wildcard policy.
- Commerce endpoint roles come from the selected active membership, not the
  account's global role. The API returns a user's active businesses at
  `/api/auth/businesses`; the frontend sends the selected ID in `X-Business-ID`.
- Legacy roles are retained without reassignment but resolve to no business
  permissions. Do not blanket-convert legacy users.
- Public Viewer registration requires the Viewer role to exist; until the
  seven-role migration is separately approved and applied, registration
  fails closed.

## Remaining authorization work

1. Implement safe business creation and membership administration with a
   role per membership; current code only resolves existing memberships.
2. Carry tenant context into database triggers/audit records and review the
   Phase 7 composite constraints for transaction and inventory lifecycle.
3. Keep global vehicle/history and Super Admin global operations explicitly
   separate from business-scoped commerce APIs.
4. Add tenant-scoped member administration for business Admins and Business
   Owners.
5. Expand cross-business denial tests across all roles and rerun them on a
   fresh PostgreSQL 18 clone before shared deployment.
