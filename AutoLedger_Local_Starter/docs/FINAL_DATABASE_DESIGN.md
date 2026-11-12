# AutoLedger Final Database Design

**Status:** Current-schema documentation plus proposed future design. The
live database was inspected read-only on 2026-11-09. No proposed migration was
executed.

## Live PostgreSQL schema

The configured database is `autoledger_db` on PostgreSQL 18.6, port `2005`.
Its `public` schema has 16 base tables, 95 columns, 16 primary keys, 14
foreign keys, 5 unique constraints, 14 check constraints, 46 indexes, 4
views, and 13 named row triggers. Table definitions, column nullability,
constraints, indexes, views, and existing relationships are detailed in
[DATABASE_ARCHITECTURE.md](./DATABASE_ARCHITECTURE.md) and
[ER_DIAGRAM.md](./ER_DIAGRAM.md).

The current tables are:

`audit_logs`, `customers`, `documents`, `inspections`, `mileage_records`,
`owners`, `ownership_records`, `purchases`, `repair_records`, `roles`,
`sales`, `service_records`, `suppliers`, `users`, `vehicles`, and
`verification_records`.

The current catalog has five legacy roles: Admin, Dealer, Inspector,
Owner/Viewer, and Verification User. The current schema has no businesses,
business memberships, inventory state table, purchase/sale line items, or
payment event table. The `purchases` and `sales` headers are empty and have no
vehicle relations.

## Existing relationship rules

- `vehicles` is the shared identity parent for vehicle history.
- Service, repair, mileage, inspection, document, verification, and ownership
  rows reference the existing vehicle identity.
- Ownership history is separate from dealership sales. A customer is never
  automatically made an owner.
- `purchases.supplier_id` references `suppliers`; `sales.customer_id`
  references `customers`. Both header references are currently nullable.
- Audit entries can retain a null actor when the user row is removed, with
  restrictive/delete behavior documented in the live architecture report.

## Proposed additive dealership model

These are design-only objects in `db/proposed_phase4/` and
`db/proposed_phase7/`; they are not live schema.

- Keep `vehicles` as the shared vehicle identity/history key. Only Super
  Admin may create or correct globally shared vehicle identity/history. A
  business-request/review flow for unknown VINs is not implemented.
- `vehicle_inventory` stores current stock state and business-specific
  condition/asking-price information for explicitly onboarded vehicles.
- `purchases` and `sales` remain transaction headers. `purchase_items` and
  `sale_items` store one vehicle/price snapshot per transaction line.
- `payments` stores payment/refund events referencing exactly one purchase or
  sale; balances are derived from completed payment events.
- `businesses` and `business_memberships` establish the approved shared
  database/multi-business model. Membership role is per business, while
  vehicle identity/history is shared and read-only to business roles.
- Nullable `business_id` values intentionally leave historical records
  unassigned until a deliberate mapping is approved.
- Composite foreign keys are drafted to prevent transaction headers,
  customers/suppliers, sale items, inventory, and payments from crossing
  tenant boundaries.

## Constraints and transaction strategy

The Phase 4 drafts specify restrictive transaction FKs, unique transaction
references, one line per vehicle per transaction, nonnegative prices,
discount/tax validation, and stock-state checks. Sale workflows lock vehicle
and inventory rows in stable vehicle-ID order, reserve stock, and complete the
sale atomically. Payment amounts are checked against outstanding balances in
the application transaction.

These constraints protect data only if the corresponding migration and
tenant-aware application logic are reviewed and installed together. The
current live schema does not enforce the proposed rules.

## Migration and data preservation

1. Recheck schema drift and make a fresh verified PostgreSQL 18 backup.
2. Restore the backup to a separate disposable database and review all
   proposed SQL definitions and dependencies.
3. Implement and verify membership resolution, active-business selection,
   tenant filters on every business query, and tenant-aware audit/workflow
   triggers.
4. Choose an explicit policy for unmapped historic records; do not infer
   business ownership from user, vehicle, owner, or timestamp data.
5. Test restore, migrations, constraints, application workflows, and
   cross-business denial on the isolated database.
6. Request separate explicit approval before applying any live migration.

Rollback must be an approved compensating migration or a controlled restore
procedure. Do not remove populated financial/history tables during an
application rollback.

## Known compatibility and design risks

- A correct schema without tenant-scoped API queries does not provide tenant
  isolation.
- The tenant draft is not deployable alone and has not been validated against
  a fresh PostgreSQL 18 restore.
- Current table uniqueness and trigger behavior must be reviewed where the
  tenant design adds composite keys and nullable tenant fields.
- Cross-business vehicle transfers and ownership of global vehicle identity
  require a dedicated workflow decision.
- Existing live role rows are not compatible with the new seven-role policy
  until reviewed migration and user-by-user reassignment.

See [FINAL_ER_DIAGRAM.md](./FINAL_ER_DIAGRAM.md) for separate current and
proposed relationship diagrams.
