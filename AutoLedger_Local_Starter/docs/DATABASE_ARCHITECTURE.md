# AutoLedger Database Architecture

## Verification scope

This document reflects a fresh, read-only catalog inspection of the configured
`autoledger_db` database on **2026-11-07**. The server reported PostgreSQL
**18.6**, database `autoledger_db`, schema `public`, port `2005`, and an
approximate database size of **10 MB**. Schema definitions were read from
`information_schema` and PostgreSQL catalogs; row counts were read with
`COUNT(*)`. No records or schema objects were changed.

The live public schema contains **16 base tables, 95 columns, 16 primary keys,
14 foreign keys, 5 unique constraints, 14 check constraints, 46 indexes, 4
views, and 13 named row triggers** (37 event/timing entries). The table counts
at verification time are listed in the inventory below.

## Table and column inventory

Types, nullability, defaults, and identity/sequence generation below are taken
from the live catalog. `PK` means primary key; `FK` identifies the referenced
column; `UK` means a unique constraint/index. Columns without an explicit
default have no catalog default.

| Table | Rows | Columns |
|---|---:|---|
| `audit_logs` | 316 | `audit_id integer PK GENERATED ALWAYS`; `user_id integer FK -> users.user_id NULL`; `action varchar(50) NOT NULL`; `entity_name varchar(100) NOT NULL`; `entity_id integer NULL`; `action_timestamp timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP`; `details text NULL` |
| `customers` | 2 | `customer_id integer PK DEFAULT nextval('customers_customer_id_seq')`; `customer_name varchar(150) NOT NULL`; `phone varchar(30) NULL`; `email varchar(150) NULL` |
| `documents` | 78 | `document_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `document_type varchar(50) NOT NULL`; `document_number varchar(100) NULL`; `issue_date date NULL`; `expiry_date date NULL`; `status varchar(20) NOT NULL DEFAULT 'VALID'` |
| `inspections` | 40 | `inspection_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `inspector_id integer FK -> users.user_id NOT NULL`; `inspection_date date NOT NULL`; `result varchar(20) NOT NULL`; `remarks text NULL` |
| `mileage_records` | 116 | `mileage_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `recorded_date date NOT NULL`; `mileage integer NOT NULL`; `source varchar(30) NOT NULL` |
| `owners` | 39 | `owner_id integer PK GENERATED ALWAYS`; `full_name varchar(100) NOT NULL`; `phone varchar(30) NULL`; `email varchar(150) NULL`; `created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `ownership_records` | 41 | `ownership_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `owner_id integer FK -> owners.owner_id NOT NULL`; `start_date date NOT NULL`; `end_date date NULL`; `ownership_status varchar(20) NOT NULL DEFAULT 'ACTIVE'` |
| `purchases` | 0 | `purchase_id integer PK DEFAULT nextval('purchases_purchase_id_seq')`; `supplier_id integer FK -> suppliers.supplier_id NULL`; `purchase_date date NOT NULL`; `total_amount numeric(12,2) NULL` |
| `repair_records` | 38 | `repair_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `repair_date date NOT NULL`; `repair_type varchar(100) NOT NULL`; `description text NULL`; `cost numeric(12,2) NULL`; `workshop_name varchar(150) NULL` |
| `roles` | 5 | `role_id integer PK GENERATED ALWAYS`; `role_name varchar(50) NOT NULL UK`; `description varchar(255) NULL` |
| `sales` | 0 | `sale_id integer PK DEFAULT nextval('sales_sale_id_seq')`; `customer_id integer FK -> customers.customer_id NULL`; `sale_date date NOT NULL`; `total_amount numeric(12,2) NULL` |
| `service_records` | 97 | `service_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `service_date date NOT NULL`; `service_type varchar(100) NOT NULL`; `mileage integer NULL`; `workshop_name varchar(150) NULL`; `notes text NULL`; `cost numeric(12,2) NULL` |
| `suppliers` | 2 | `supplier_id integer PK DEFAULT nextval('suppliers_supplier_id_seq')`; `supplier_name varchar(150) NOT NULL`; `phone varchar(30) NULL`; `email varchar(150) NULL` |
| `users` | 7 | `user_id integer PK GENERATED ALWAYS`; `role_id integer FK -> roles.role_id NOT NULL`; `full_name varchar(100) NOT NULL`; `email varchar(150) NOT NULL UK`; `phone varchar(30) NULL`; `is_active boolean NOT NULL DEFAULT true`; `created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP`; `password_hash varchar(255) NULL` |
| `vehicles` | 41 | `vehicle_id integer PK GENERATED ALWAYS`; `vin varchar(17) NOT NULL UK`; `registration_no varchar(30) NOT NULL UK`; `brand varchar(50) NOT NULL`; `model varchar(50) NOT NULL`; `model_year integer NOT NULL`; `color varchar(30) NULL`; `fuel_type varchar(20) NULL`; `transmission varchar(20) NULL`; `engine_no varchar(50) NULL UK`; `created_at timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `verification_records` | 40 | `verification_id integer PK GENERATED ALWAYS`; `vehicle_id integer FK -> vehicles.vehicle_id NOT NULL`; `verified_by integer FK -> users.user_id NOT NULL`; `verification_date date NOT NULL`; `result varchar(20) NOT NULL`; `remarks text NULL` |

`varchar(n)` above is shorthand for the live `character varying(n)` type.
Identity columns are `GENERATED ALWAYS AS IDENTITY`; purchases, sales,
suppliers, and customers use sequence-backed defaults instead.

## Primary keys, foreign keys, and relationships

All tables have a single-column primary key, listed in the inventory. The
following 14 foreign keys are declared:

| Child column | Parent column | Delete behavior |
|---|---|---|
| `audit_logs.user_id` | `users.user_id` | `SET NULL` |
| `documents.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `inspections.inspector_id` | `users.user_id` | `RESTRICT` |
| `inspections.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `mileage_records.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `ownership_records.owner_id` | `owners.owner_id` | `RESTRICT` |
| `ownership_records.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `purchases.supplier_id` | `suppliers.supplier_id` | PostgreSQL default `NO ACTION` |
| `repair_records.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `sales.customer_id` | `customers.customer_id` | PostgreSQL default `NO ACTION` |
| `service_records.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |
| `users.role_id` | `roles.role_id` | `RESTRICT` |
| `verification_records.verified_by` | `users.user_id` | `RESTRICT` |
| `verification_records.vehicle_id` | `vehicles.vehicle_id` | `RESTRICT` |

Each child FK is single-column and not unique, so it expresses many child rows
per parent, not a one-to-one relationship. An FK column being nullable allows
the child row to have no parent for that reference. Specifically,
`audit_logs.user_id`, `purchases.supplier_id`, and `sales.customer_id` are
nullable; the other FK columns are not. Ownership history is one-to-many in
general, with an additional unique partial index enforcing at most one active
owner record per vehicle.

## Unique and check constraints

The catalog reports five unique constraints:

- `roles_role_name_key`: `roles(role_name)`.
- `users_email_key`: `users(email)`.
- `vehicles_vin_key`: `vehicles(vin)`.
- `vehicles_registration_no_key`: `vehicles(registration_no)`.
- `vehicles_engine_no_key`: `vehicles(engine_no)`.

There is also a unique index (not a declared unique constraint),
`uq_owners_name_email` on `owners(full_name, email)`. The unique partial index
`uq_ownership_one_active_per_vehicle` covers
`ownership_records(vehicle_id) WHERE ownership_status = 'ACTIVE'`.

Fourteen check constraints are declared:

- `documents.chk_document_dates`: expiry date is null, issue date is null, or
  expiry date is on/after issue date.
- `documents.chk_document_status`: status is one of `VALID`, `EXPIRED`,
  `PENDING`, `CANCELLED`.
- `inspections.chk_inspection_result`: result is one of `PASS`, `FAIL`,
  `CONDITIONAL`, `PENDING`.
- `mileage_records.chk_mileage_source`: source is one of `SERVICE`,
  `INSPECTION`, `OWNER`, `DEALER`, `OTHER`.
- `mileage_records.chk_mileage_value`: mileage is nonnegative.
- `ownership_records.chk_ownership_dates`: end date is null or on/after start
  date.
- `ownership_records.chk_ownership_status`: status is one of `ACTIVE`,
  `TRANSFERRED`, `ENDED`.
- `purchases.purchases_total_amount_check`: total amount is nonnegative.
- `repair_records.chk_repair_cost`: cost is null or nonnegative.
- `sales.sales_total_amount_check`: total amount is nonnegative.
- `service_records.chk_service_cost_nonnegative`: cost is null or nonnegative.
- `service_records.chk_service_mileage`: mileage is null or nonnegative.
- `vehicles.chk_vehicle_year`: model year is between 1980 and 2035 inclusive.
- `verification_records.chk_verification_result`: result is one of
  `VERIFIED`, `REJECTED`, `PENDING`, `CONDITIONAL`.

## Indexes

The live catalog lists 46 indexes. Primary-key, unique-constraint, and
standalone/partial indexes are all included here.

| Table | Index | Keys / predicate |
|---|---|---|
| `audit_logs` | `audit_logs_pkey` | unique `(audit_id)` |
| `audit_logs` | `idx_audit_timestamp` | `(action_timestamp DESC)` |
| `audit_logs` | `idx_audit_user` | `(user_id)` |
| `customers` | `customers_pkey` | unique `(customer_id)` |
| `documents` | `documents_pkey` | unique `(document_id)` |
| `documents` | `idx_document_vehicle` | `(vehicle_id)` |
| `documents` | `idx_documents_expiry_date` | `(expiry_date) WHERE expiry_date IS NOT NULL` |
| `inspections` | `inspections_pkey` | unique `(inspection_id)` |
| `inspections` | `idx_inspection_vehicle` | `(vehicle_id)` |
| `inspections` | `idx_inspections_date` | `(inspection_date DESC)` |
| `inspections` | `idx_inspections_inspector` | `(inspector_id)` |
| `mileage_records` | `mileage_records_pkey` | unique `(mileage_id)` |
| `mileage_records` | `idx_mileage_vehicle` | `(vehicle_id)` |
| `mileage_records` | `idx_mileage_vehicle_latest` | `(vehicle_id, recorded_date DESC, mileage_id DESC) INCLUDE (mileage)` |
| `owners` | `owners_pkey` | unique `(owner_id)` |
| `owners` | `idx_owners_created` | `(created_at DESC)` |
| `owners` | `uq_owners_name_email` | unique `(full_name, email)` |
| `ownership_records` | `ownership_records_pkey` | unique `(ownership_id)` |
| `ownership_records` | `idx_ownership_owner` | `(owner_id)` |
| `ownership_records` | `idx_ownership_start_date` | `(start_date DESC)` |
| `ownership_records` | `idx_ownership_vehicle` | `(vehicle_id)` |
| `ownership_records` | `idx_ownership_vehicle_active` | `(vehicle_id, start_date DESC) WHERE ownership_status = 'ACTIVE'` |
| `ownership_records` | `uq_ownership_one_active_per_vehicle` | unique `(vehicle_id) WHERE ownership_status = 'ACTIVE'` |
| `purchases` | `purchases_pkey` | unique `(purchase_id)` |
| `repair_records` | `repair_records_pkey` | unique `(repair_id)` |
| `repair_records` | `idx_repair_vehicle` | `(vehicle_id)` |
| `repair_records` | `idx_repair_vehicle_date_cost` | `(vehicle_id, repair_date DESC) INCLUDE (cost)` |
| `roles` | `roles_pkey` | unique `(role_id)` |
| `roles` | `roles_role_name_key` | unique `(role_name)` |
| `sales` | `sales_pkey` | unique `(sale_id)` |
| `service_records` | `service_records_pkey` | unique `(service_id)` |
| `service_records` | `idx_service_vehicle` | `(vehicle_id)` |
| `service_records` | `idx_service_vehicle_date_cost` | `(vehicle_id, service_date DESC) INCLUDE (cost)` |
| `suppliers` | `suppliers_pkey` | unique `(supplier_id)` |
| `users` | `users_pkey` | unique `(user_id)` |
| `users` | `users_email_key` | unique `(email)` |
| `users` | `idx_users_active` | `(is_active)` |
| `users` | `idx_users_role` | `(role_id)` |
| `vehicles` | `vehicles_pkey` | unique `(vehicle_id)` |
| `vehicles` | `vehicles_engine_no_key` | unique `(engine_no)` |
| `vehicles` | `vehicles_registration_no_key` | unique `(registration_no)` |
| `vehicles` | `vehicles_vin_key` | unique `(vin)` |
| `verification_records` | `verification_records_pkey` | unique `(verification_id)` |
| `verification_records` | `idx_verification_date` | `(verification_date DESC)` |
| `verification_records` | `idx_verification_vehicle` | `(vehicle_id)` |
| `verification_records` | `idx_verification_verified_by` | `(verified_by)` |

## Views

Four views are present:

- `vw_vehicle_summary`: vehicle identity plus active owner, latest mileage,
  last service, document count/statuses, and next unexpired document date.
- `vw_expiring_documents`: non-cancelled documents expiring between the
  current date and 30 days ahead, joined to vehicle registration/VIN, with
  days-until-expiry.
- `vw_monthly_costs`: monthly service and repair totals/counts, combined with
  a full outer join so months present in either ledger are represented.
- `vw_owner_history`: owner, vehicle, and dated ownership history joined
  together.

## Triggers

The live catalog reports 13 named row triggers (37 operation/timing entries):

| Table | Trigger | Timing / events | Effect |
|---|---|---|---|
| `documents` | `trg_audit_documents` | AFTER INSERT, UPDATE, DELETE | Writes a row snapshot to `audit_logs` via `audit_ledger_row_change()`; excludes `password_hash` from row snapshots. |
| `documents` | `trg_document_expiry_status` | BEFORE INSERT, UPDATE | Marks a non-cancelled document expired when its expiry date is before `CURRENT_DATE`. |
| `inspections` | `trg_audit_inspections` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `mileage_records` | `trg_audit_mileage_records` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `mileage_records` | `trg_mileage_no_rollback` | BEFORE INSERT, UPDATE | `prevent_mileage_rollback()` rejects a reading lower than the latest reading for its vehicle. |
| `owners` | `trg_audit_owners` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `ownership_records` | `trg_audit_ownership_records` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `repair_records` | `trg_audit_repair_records` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `roles` | `trg_audit_roles` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `service_records` | `trg_audit_service_records` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `users` | `trg_audit_users` | AFTER INSERT, UPDATE, DELETE | Row-change audit; row snapshot omits `password_hash`. |
| `vehicles` | `trg_audit_vehicles` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |
| `verification_records` | `trg_audit_verification_records` | AFTER INSERT, UPDATE, DELETE | Row-change audit. |

The database also contains `refresh_expired_document_statuses()`, a function
that updates expired rows when called; it is not itself a trigger. The ownership
transfer function `transfer_ownership()` is also present and performs the
ownership close/insert operation transactionally. Neither is counted among the
13 triggers.

## Application architecture and schema coverage

The application is a local FastAPI service, using `psycopg2` for PostgreSQL
access and serving a single-page HTML/CSS/JavaScript frontend. The backend has
vehicle routes, an authentication router, and generic resource routes for a
fixed allowlist. The frontend implements dashboard, vehicle inventory/history,
owners, documents, inspections, verification, reports, audit, and team access.
Service, repair, and mileage records are available through vehicle-history
views/forms rather than standalone navigation modules.

### Tables without API endpoints

- `customers`, `suppliers`, `purchases`, and `sales` do not appear in the
  backend resource query/table/write allowlists and have no corresponding
  dedicated routes.
- `roles` has no direct role-management endpoint.

### Tables without frontend modules

- There are no customer, supplier, purchase, or sales pages/forms.
- Roles are not managed in a separate UI; user role assignment is part of the
  Admin team-access workflow.
- Audit logs are viewable but not directly editable; this is appropriate for
  an audit trail.

### CRUD coverage and workflow gaps

- Vehicles have list/create/read/update/delete API routes. Deletes are
  constraint-limited by related history.
- Owners and mutable service, repair, mileage, inspection, document, and
  verification resources use generic list/read/create/patch/delete routes.
  Application authorization narrows who can write; delete is Admin-only.
- Ownership history is readable, but direct ownership edits/deletes are
  intentionally not exposed. Transfers use the dedicated atomic transfer
  workflow, preserving the history model.
- Users have Admin-only list/create/read/update-access routes; no user-delete
  route is present. Roles have no CRUD routes.
- Audit records have read/list routes only.
- Purchases/sales have no API or frontend functionality; the database itself
  has only header columns and lacks line items and a relationship to vehicles.
  Therefore it cannot record which vehicle(s) were bought or sold, and does
  not define transaction-level vehicle inventory effects.

### Authentication and authorization observations

- The backend uses signed bearer tokens and loads active user/role data when
  resolving the current user. Role checks are enforced at route dependencies
  and resource-write allowlists; Admin access is required for user management
  and audit reads.
- The database currently contains `Admin`, `Dealer`, `Inspector`,
  `Owner/Viewer`, and `Verification User` roles. Backend role models and
  permission allowlists recognize the first four only; the existing
  `Verification User` role has no matching permission policy in the code.
- The Admin account bootstrap is limited to the configured existing Admin
  account before an Admin password exists. Viewer registration creates
  read-only role accounts. The JWT key is expected from environment
  configuration.
- The current permission matrix is application-level; it is not expressed as
  PostgreSQL row-level security policies.

## Normalization observations

- Core entities are separated: vehicles, owners, users/roles, suppliers, and
  customers are distinct from their dated or transactional records.
- Ownership is modeled as a junction/history table with dates and status,
  allowing multiple past owners without repeating owner or vehicle attributes.
- Service, repair, mileage, inspection, document, and verification events are
  stored as vehicle-linked records rather than repeating columns on `vehicles`.
- `users.role_id`, event-to-vehicle FKs, and transaction-to-party FKs represent
  declared references; referential integrity is checked by PostgreSQL.
- The schema is reasonably normalized for the vehicle-history domain. The
  purchase/sale portion is incomplete rather than demonstrably denormalized:
  transaction totals exist without detail/line-item tables, and no vehicle FK
  identifies the transaction's inventory items.
- `owners` and `customers` are separate contact records with overlapping
  name/contact concepts. Whether they represent different business roles or
  should share a party model is a domain decision; the current schema does not
  declare a relationship between them.
- `total_amount` is stored directly on purchases and sales. With no line items,
  the catalog does not define whether it is an entered amount or a derived
  total, so its consistency cannot be assessed from the schema alone.

## Current database limitations

1. Purchases and sales have zero rows at inspection time and no transaction
   detail/vehicle linkage. Supplier/customer references are nullable.
2. There are no line-item tables, transaction status/payment fields, or
   transaction-to-vehicle relations in the inspected schema.
3. There are no unique constraints on supplier/customer contact fields. The
   schema permits duplicate email/phone values for those entities.
4. `uq_owners_name_email` is a composite unique index over nullable email;
   PostgreSQL permits multiple rows where a unique-index key contains NULL.
5. Date constraints protect individual ownership intervals, but do not by
   themselves prevent overlaps between historical intervals. The partial
   unique index only enforces one currently `ACTIVE` row per vehicle.
6. Ownership history, audit history, and other vehicle-event references use
   restrictive delete behavior, which protects existing records but means
   deleting a linked vehicle/owner/user may be rejected.
7. Row counts are a snapshot from this inspection and can change. They should
   not be treated as migration baselines without a separately approved backup
   and migration process.

## Phase 3 recommendations (not performed)

- Before any schema change, obtain approval, create and verify a restorable
  database backup, and establish a rollback procedure.
- Define the purchase/sale business model first: how multiple vehicles per
  transaction, acquisition/sale price per vehicle, supplier/customer roles,
  dates, and inventory state should be represented.
- Prepare additive migrations only after reviewing the target model and
  existing records; document each DDL/data operation, preconditions,
  post-migration checks, and reversal strategy. Do not remove or rewrite
  existing history as part of the initial extension.
- Align the existing `Verification User` role with an explicit authorization
  decision before exposing additional permissions or changing role records.
- Add integration tests for new transaction behavior and authorization, and
  verify the affected API/UI paths against a backed-up test database before
  applying anything to the existing database.
