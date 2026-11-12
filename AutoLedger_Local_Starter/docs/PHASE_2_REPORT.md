# AutoLedger Phase 2 Report

**Completed:** 2026-11-07

**Scope:** Architecture documentation and ER diagram only.

## Work completed

- Reconnected to the existing `.env`-configured `autoledger_db` and re-queried
  PostgreSQL 18.6's live catalog and current table counts.
- Verified all public base-table columns, data types, identity/sequence
  generation, nullability/defaults, primary and foreign keys, unique/check
  constraints, indexes, views, and row triggers.
- Replaced the prior partial ER diagram with one covering all 16 base tables,
  all 95 columns, and all 14 declared foreign keys.
- Added this catalog-backed database architecture inventory and a comparison
  of schema capability to backend and frontend coverage.
- Documented limitations and recommendations for a future, approval-gated
  Phase 3.

## Live database snapshot

Connection target: `autoledger_db`, PostgreSQL 18.6, `public`, port `2005`,
approximately 10 MB at inspection.

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

Catalog totals: **16 tables, 95 columns, 16 primary keys, 14 foreign keys, 5
unique constraints, 14 check constraints, 46 indexes, 4 views, and 13 named row
triggers** (37 trigger operation/timing entries). Five existing roles are
present: Admin, Dealer, Inspector, Owner/Viewer, and Verification User.

## ER diagram verification

The Mermaid diagram in `docs/ER_DIAGRAM.md` contains all 16 tables and each
catalog column. It marks primary, foreign, and unique keys and nullability. Its
14 relationship lines correspond to the 14 actual FKs. The relationships show
optional parent references where nullable and include the actual one-active-
ownership partial unique rule in the accompanying explanation.

Confirmed absence: purchases and sales have no vehicle foreign keys or
vehicle-bearing line-item tables. The only declared transaction party
relationships are `purchases.supplier_id -> suppliers.supplier_id` and
`sales.customer_id -> customers.customer_id`.

## Existing problems identified

1. `customers`, `suppliers`, `purchases`, and `sales` have no API resource
   routes or frontend modules. `roles` also has no direct management API.
2. Purchase and sales tables contain only header fields and are empty; they
   cannot identify purchased/sold vehicles, represent line items, or drive
   inventory movement.
3. Existing app operations cover vehicle CRUD and mutable ledger CRUD, but
   ownership is handled by the dedicated transfer workflow; audit records are
   read-only; users can be listed/created/read/updated by Admin but not
   deleted; roles have no CRUD.
4. The database role `Verification User` is not present in the backend's
   declared role schemas/permission allowlists, leaving no explicit app
   authorization policy for that existing role.
5. Existing ER content omitted the four commerce tables and was not a complete
   representation of the current live database. Prior project progress counts
   also differ from this refreshed snapshot.
6. Purchases/sales have no detail tables; stored `total_amount` cannot be
   reconciled against line items. Owner/customer models overlap in contact
   fields but have no declared relationship; their intended distinction is a
   business rule not encoded in the database.
7. The ownership date check validates each interval individually, but there is
   no database exclusion constraint preventing overlapping historical date
   ranges. The partial unique index only constrains simultaneous ACTIVE rows.

## Recommendations for Phase 3

- Obtain explicit approval, create a database backup, and verify its
  restorability before schema changes.
- Confirm business rules for purchases/sales, particularly vehicle-per-
  transaction cardinality, per-vehicle price, parties, transaction status, and
  effects on inventory/ownership history.
- Propose a reversible, additive migration design and test it against a
  restored copy; preserve current rows and history.
- Decide the permission policy for the existing Verification User role before
  modifying authorization or role data.
- Add route, schema, transaction, authorization, and UI tests for any approved
  new workflows.

No Phase 3 work was started.

## Files created or updated

- **Updated:** `docs/ER_DIAGRAM.md`
- **Created:** `docs/DATABASE_ARCHITECTURE.md`
- **Created:** `docs/PHASE_2_REPORT.md`

No application source, configuration, SQL migration, or database object was
changed. No database rows were inserted, updated, or deleted. No backup,
migration, commit, or push was performed. Existing staged and unstaged Git
changes were preserved.
