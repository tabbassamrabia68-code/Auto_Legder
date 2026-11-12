# AutoLedger Safe Migration Plan

**Prepared:** 2026-11-07

**Status:** Planning only. No migration or seed script was executed.

## 1. Current database snapshot

Rechecked read-only against `.env`-configured `autoledger_db` on PostgreSQL
18.6, host `localhost`, port `2005`, schema `public`, at approximately 10 MB.
The catalog reported **16 tables, 95 columns, 16 primary keys, 14 foreign
keys, 5 unique constraints, 14 check constraints, 46 indexes, 4 views, and 13
named row triggers** (37 event/timing entries).

| Table | Rows | Table | Rows |
|---|---:|---|---:|
| `audit_logs` | 316 | `customers` | 2 |
| `documents` | 78 | `inspections` | 40 |
| `mileage_records` | 116 | `owners` | 39 |
| `ownership_records` | 41 | `purchases` | 0 |
| `repair_records` | 38 | `roles` | 5 |
| `sales` | 0 | `service_records` | 97 |
| `suppliers` | 2 | `users` | 7 |
| `vehicles` | 41 | `verification_records` | 40 |

Purchases currently contain `purchase_id`, nullable `supplier_id`,
`purchase_date`, and nullable `total_amount`. Sales contain `sale_id`, nullable
`customer_id`, `sale_date`, and nullable `total_amount`. Their only declared
relationships are to suppliers and customers respectively. The live schema
has **no purchase-to-vehicle or sale-to-vehicle FK and no transaction line
tables**. Do not infer prior vehicle acquisitions/sales from current
`ownership_records`.

## 2. Verified backup

Before any proposed migration, a fresh custom-format backup was created
outside the repository and verified:

- **Path:** `C:\Users\rabia tabbassam\Desktop\AutoLedgerBackups\autoledger_db_20261107_191304_305.dump`
- **Created:** 2026-11-07 19:13:04.657 +05:00
- **Size:** 77,334 bytes
- **SHA-256:** `10597AAD0EF43DCB26828EC6F085A325F47DC990C129A9819B9F4FC63C4DBE47`
- **Verification:** PostgreSQL 18.6 `pg_restore --list` succeeded and
  confirmed all 16 table definitions, all 16 table-data entries, and all four
  views.

See [PHASE_3_BACKUP_REPORT.md](./PHASE_3_BACKUP_REPORT.md) for the full
verification record. `--list` is not a restore drill; restore this archive to a
separate disposable database and validate it before using it as a migration
rollback source. The prior 2026-10-12 backup remains untouched. A zero-byte
file left by an earlier failed attempt also remains untouched.

## 3. Existing SQL scripts and risks

The project has no separate migration-history table or dedicated migration
folder. The SQL files below were inspected but **not executed**.

| File | Purpose / classification | Objects affected | Data effects | Rerun and live-conflict assessment |
|---|---|---|---|---|
| `db/001_indexes.sql` | Schema migration: add service cost/check and query indexes. | Adds `service_records.cost NUMERIC(12,2)` if absent; guarded nonnegative cost check; creates indexes for inspection/verification users and vehicles, users roles, documents, ownership, audit, service, repair, and mileage. | No direct row insert/update/delete. | Mostly repeatable (`IF NOT EXISTS` and guarded constraint). `IF NOT EXISTS` checks object names, not that an existing same-name index has the intended definition. Depends on the existing base tables/columns. In the live schema, the column, check, and named indexes are already present; compare definitions before any reapplication. |
| `db/002_triggers.sql` | Trigger/function schema migration, with a data-changing expiry refresh. | Replaces mileage, audit, and document-status functions; drops/recreates mileage, vehicle, ownership, and document triggers. | Calls `refresh_expired_document_statuses()`, which updates overdue `documents.status` values to `EXPIRED`. If comprehensive document auditing is installed, that update can also append audit rows through the existing audit trigger. | Trigger recreation is repeatable structurally, but the status refresh is not necessarily side-effect-free. **Order-sensitive conflict:** its `audit_ledger_row_change()` version selects `vehicle_id` only for `vehicles` and otherwise reads `ownership_id`. The live `007` version correctly maps keys for several entity tables. Replacing it with `002` while comprehensive audit triggers remain can record NULL `entity_id` for unrelated audited tables until `007` replaces it again. The helper commits each numbered script independently, so a failure between `002` and `007` can leave this interim behavior installed. It can also change document rows and create audit entries. |
| `db/003_ownership_transfer.sql` | Schema/function migration for ownership transfer integrity. | Creates the partial unique index on active ownership per vehicle; replaces `transfer_ownership(integer, integer, date)`. | No direct DML when defining the function. Calling the function later updates/inserts ownership rows. | Index/function definitions are generally repeatable, but same-name object drift is not repaired by `IF NOT EXISTS`. Requires the existing ownership/vehicle/owner columns. The live partial index and transfer function are already present; do not apply without reviewing their current definitions and the surrounding trigger behavior. |
| `db/004_views.sql` | Reporting/read-model schema script. | Creates or replaces `vw_vehicle_summary`, `vw_expiring_documents`, `vw_monthly_costs`, and `vw_owner_history`. | No direct row DML. | Repeatable when output columns remain compatible. `CREATE OR REPLACE VIEW` can fail if a replacement changes existing output-column names/order/types incompatibly, and dependent objects may constrain changes. All four views exist live. |
| `db/005_demo_seed.sql` | Demo seed/data script, not a pure schema migration. | `service_records.cost`; inserts rows into `documents` for the lowest vehicle ID. | Updates NULL service costs using a formula; conditionally inserts demo expiring/expired documents. These changes are real persistent DML, not test-only data. Document existence checks use reference values but no unique constraint is declared on `document_number`. | **Not safe for routine production application.** It fills unknown costs with synthetic demo amounts and adds document records. Repeated sequential runs usually avoid duplicate references, but it is not concurrency-safe and may re-update any cost later set NULL. Current document/service counts are not permission to run it. Do not seed the live database. |
| `db/006_authentication.sql` | Authentication schema/data migration. | Adds nullable `users.password_hash` if absent; ensures an `Owner/Viewer` row exists in `roles`. | May insert the `Owner/Viewer` role if missing. | Generally repeatable: column addition is guarded and role insert uses `ON CONFLICT (role_name) DO NOTHING`. Still depends on `users`, `roles`, and the unique role-name constraint; it does not resolve other legacy role policies. The live column and role already exist. |
| `db/007_comprehensive_audit.sql` | Audit function and trigger schema migration. | Replaces `audit_ledger_row_change()` and drops/recreates audit triggers for roles, users, owners, vehicles, ownership, service, repair, mileage, inspections, documents, and verification. | No direct table-row DML apart from DDL; future trigger calls insert audit records. | Repeatable in isolation, but it mutates the trigger/function state and should remain ordered after `002`. It does not add audit triggers for customers, suppliers, purchases, or sales. Reapplying it after `002` restores the comprehensive key mapping, but cannot repair audit rows already recorded with missing/wrong entity IDs. |
| `docs/queries.sql` | Read-only reporting/demo query collection; not a migration. | Reads current views and vehicle/history tables. | The active statements are SELECT/CTE reads. One commented-out example is an INSERT intended to demonstrate mileage rollback if manually enabled. | Active statements are read-only; do not uncomment or execute the sample INSERT against production. The query file is not part of `db/*.sql` migration execution. |

### Migration helper assessment

`db/reset_and_reseed.ps1` was also inspected as the runner, not executed. It
sorts and applies every `db/*.sql` file through `psql`; it does not create or
verify a backup first, does not record per-migration completion, and treats
the data-changing demo seed as part of the same sequence. Each SQL file has
its own transaction, so the complete sequence is not one atomic transaction.
Its success message describes the result as current even though it has no
schema-version check. Do not use this helper for a live migration without a
separately approved, reviewed process. The filename should not be read as
evidence that it safely resets or restores data; its current action is to run
the numbered SQL scripts.

## 4. Proposed future schema changes (not implemented)

The narrow proposal is to add two detail tables, preserving existing header
tables and rows:

1. **`purchase_items`**: generated primary key; required `purchase_id` FK to
   `purchases`; required `vehicle_id` FK to `vehicles`; required nonnegative
   `unit_cost NUMERIC(12,2)`.
2. **`sale_items`**: generated primary key; required `sale_id` FK to `sales`;
   required `vehicle_id` FK to `vehicles`; required nonnegative
   `unit_price NUMERIC(12,2)`.

Each row would represent one specific vehicle on a purchase or sale. A
transaction header could therefore have multiple vehicles, and each detail
row would preserve the price for that vehicle at that event. A unique
`(purchase_id, vehicle_id)` and `(sale_id, vehicle_id)` would prevent the same
vehicle appearing twice in one header, while allowing a vehicle to have
multiple distinct purchase/sale events over its lifetime. Do **not** make
`vehicle_id` globally unique in either detail table; that would prevent a
future reacquisition or resale.

This design is proposed, not current schema. Its purpose is to connect existing
transaction headers to actual inventory units without replacing existing
vehicle identity or ownership history. Because each vehicle is already an
individual inventory record with a VIN, a line quantity is not proposed.
Whether all transactions must have at least one item, whether a vehicle may be
entered before purchase capture, and how historical opening stock is represented
must be decided first.

### Transaction consistency and inventory

- Keep the existing `purchases.total_amount` and `sales.total_amount` columns
  for compatibility. New transaction services should derive their totals from
  item prices inside the same transaction, rather than accepting an unrelated
  caller-supplied total. Add a reconciliation check in application/tests; any
  eventual database enforcement must account for the fact that ordinary CHECK
  constraints cannot sum child rows.
- Purchase/sale API operations should lock the affected vehicle row
  (`SELECT ... FOR UPDATE`) and write header, detail, and any approved
  ownership/inventory event atomically. Define duplicate/current-inventory
  checks under that lock to prevent concurrent contradictory transactions.
- The database currently has no inventory-status column/state machine and no
  purchase/sale vehicle history. The 41 existing vehicles therefore have
  **unknown purchase provenance** from this schema. Do not fabricate purchase
  rows or infer acquisition dates/prices from owners, creation timestamps, or
  ownership events.
- `customers` and `owners` are separate tables and have no FK between them.
  Do not automatically turn a customer into an owner until the business rule
  and identity mapping are approved. Decide whether sale should also create or
  transfer an ownership record.

## 5. FK and constraint strategy

If approved after business-rule decisions:

- Use `NOT NULL` for each detail row's transaction header, vehicle, and unit
  amount so orphan/price-less transaction lines cannot be created.
- Use `ON DELETE RESTRICT` for transaction and vehicle references so deleting a
  header or inventory record cannot erase financial/history details.
- Add nonnegative amount checks for `unit_cost` and `unit_price`.
- Add unique transaction/vehicle pairs to block duplicate copies within one
  transaction while supporting repeated transactions at different times.
- Add indexes supporting each FK/history path. A unique index beginning with
  the header FK can support header lookup; add a separate `vehicle_id` index
  for vehicle transaction history. Verify need with query plans before adding
  extra indexes.
- Keep current header FK behavior to supplier/customer unchanged unless a
  separate compatibility decision approves tightening nullable columns.
- Consider idempotency keys or request identifiers in API design separately;
  no such current database columns are confirmed.

## 6. Data-preservation strategy

1. Take a new verified backup immediately before the eventual migration; this
   report's archive is a planning baseline, not a perpetual guarantee.
2. Restore the backup to an isolated, disposable PostgreSQL 18 database and
   verify table counts, schema, constraints, views, and representative rows
   before testing any migration.
3. Capture current row counts and stable key-range/checksum evidence for every
   affected table immediately before the change. Do not use only aggregate
   counts where existing-row identity matters.
4. Make the first proposed extension additive: create new detail tables,
   constraints, and indexes only. Do not alter/delete existing vehicles,
   owners, customers, suppliers, purchase/sale headers, or history.
5. At migration time, re-check purchase/sale row counts. They were zero at this
   snapshot, but may no longer be empty. Do not assume there are no headers or
   backfill data unless a new live check proves it.
6. Do not manufacture vehicle-to-transaction history for existing vehicles.
   Record legacy opening inventory only through an explicitly approved and
   evidenced business process.
7. Preserve audit history and establish approved audit coverage for new
   commerce tables; do not allow migration-trigger side effects to obscure
   actors or record identifiers.

## 7. Rollback strategy

- The proposed first migration is additive and should leave existing
  application behavior working. If application validation fails, disable the
  new transaction routes and revert application release while leaving the new
  tables and data intact.
- Prefer a forward corrective migration over deleting populated transaction
  history. Do not automatically drop new tables during rollback.
- If a full recovery is necessary, restore the verified archive into a
  separate new database, validate it, and perform any cutover only with
  explicit approval. Never restore over or recreate the existing live database
  as an automatic rollback step.
- Prepare and review a down-script only for an isolated test database where
  the new tables are demonstrably empty. A live down-script that could remove
  recorded transactions is not an acceptable default.
- The custom archive's TOC listing succeeded, but a separate-database restore
  drill is still required before treating restore as operationally proven.

## 8. Future execution order

No step below was executed in this phase.

1. Obtain approval for transaction semantics, vehicle ownership effects,
   historical opening inventory, and role policy.
2. Re-inspect live schema and counts; review the migration SQL and confirm
   there is no name/type/index drift.
3. Create and verify a fresh backup; restore it to a disposable database.
4. Run preflight queries on the restored copy (FK integrity, current purchase
   and sale header counts, existing vehicles lacking transaction history).
5. Apply an additive migration that creates the approved purchase/sale detail
   tables, FKs, checks, unique pairs, and only justified indexes. Do not run
   the demo seed script or the all-scripts helper.
6. Run post-migration schema, constraint, index, and data-preservation
   comparisons on the test copy.
7. Test transactional API logic and UI in the isolated environment, including
   concurrent duplicate purchase/sale attempts and rollback on a failing line.
8. Schedule an approved maintenance window; take/verify a fresh backup and
   capture before-state evidence.
9. Apply only the reviewed versioned migration, with `ON_ERROR_STOP`, error
   logging that excludes credentials, and a clear abort path.
10. Run post-deployment checks and a read-only smoke test. Keep new routes
    disabled until checks pass; observe logs and counts before enabling them.

## 9. Testing and verification plan

- Restore drill: `pg_restore` to a new isolated database, then compare object
  and row counts with the archive snapshot; verify key views and functions.
- Schema assertions: both detail tables exist with intended columns, PK/FKs,
  delete actions, nonnegative checks, uniqueness, and indexes. Confirm no
  existing table was dropped/renamed and existing columns were not rewritten.
- Data preservation: compare stable primary-key sets and row checksums for all
  pre-existing tables; verify baseline transaction headers and all vehicle,
  owner, ownership, and audit records remain unchanged.
- Referential integrity: attempt invalid parent references in a rolled-back
  test transaction; verify FK rejection and delete restriction.
- Transaction behavior: create purchase/sale headers and multiple vehicle
  items atomically; verify computed totals; force an invalid line and prove the
  entire operation rolls back. Test the chosen repeated acquisition/resale
  policy and concurrent writes.
- Authorization: test each role against supplier/customer/transaction endpoints,
  including the existing `Verification User` account once policy is agreed.
- API/UI integration: validate searching/filtering/reporting on real test data
  and ensure transaction views clearly represent per-vehicle prices/history.
- Production verification: health/read-only queries, counts, no orphan
  references, expected audit rows, and user-facing smoke checks. Do not use
  seed data in the live database.

## 10. Risks and unresolved questions

1. Can one purchase/sale contain multiple vehicles? Proposed line tables allow
   multiple unit rows; confirm this.
2. Can vehicles be reacquired and resold multiple times? Proposed unique keys
   are per header/vehicle, not global; define how to prevent selling a vehicle
   that is not currently in stock.
3. Should sale create/close an `ownership_records` period? Customers and owners
   are currently separate entities, so this needs an explicit rule or mapping.
4. Is inventory ever added without a supplier purchase record (opening stock,
   trade-in, correction)? The current schema cannot identify such provenance.
5. Are amount fields always PKR? The frontend formats PKR, but current purchase
   and sales tables contain no currency column. Confirm before locking in
   monetary semantics.
6. Are taxes, fees, discounts, deposits, returns, cancellations, or payments in
   scope? The current headers have no fields for these.
7. Is a transaction header always final on creation, or can it be draft or
   cancelled? Current tables have no status column.
8. The `002` trigger migration temporarily replaces comprehensive audit key
   mapping and refreshes expired-document rows. The migration runner executes
   scripts in separate transactions and does not back up first; avoid rerunning
   the sequence as a live deployment mechanism.
9. The environment also contains an older 2026-10-12 dump and a zero-byte file
   from a failed attempt. Both were left untouched; use only the verified
   timestamped archive listed in the backup report for the current plan.

## Scope and safety confirmation

This document records proposed future work only. The fresh backup was created
outside the repository and successfully listed. Catalog inspection was
read-only. No SQL migration, query file, or seed script was executed; no live
database rows or schema objects were modified; no application code was changed.
Only the two Phase 3 documentation files are intended additions for this
phase. No Phase 4 work has started.
