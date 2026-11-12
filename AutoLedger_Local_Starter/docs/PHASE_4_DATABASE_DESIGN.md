# AutoLedger Phase 4 Database Design

**Status:** Proposed design only. No SQL in `db/proposed_phase4/` has been
executed. The live database, application, and existing backup were not
modified.

## 1. Current schema overview

A read-only catalog and row-count query was run against the existing
`.env`-configured `autoledger_db` on 2026-11-07. It reported PostgreSQL 18.6,
schema `public`, host `localhost`, port `2005`, and approximately 10 MB. The
snapshot contained 16 base tables, 95 columns, 16 primary keys, 14 foreign
keys, 5 unique constraints, 14 check constraints, 46 indexes, 4 views, and 13
named row triggers.

| Existing table | Rows |
|---|---:|
| `audit_logs` | 316 |
| `customers` | 2 |
| `documents` | 78 |
| `inspections` | 40 |
| `mileage_records` | 116 |
| `owners` | 39 |
| `ownership_records` | 41 |
| `purchases` | 0 |
| `repair_records` | 38 |
| `roles` | 5 |
| `sales` | 0 |
| `service_records` | 97 |
| `suppliers` | 2 |
| `users` | 7 |
| `vehicles` | 41 |
| `verification_records` | 40 |

Existing purchase columns are `purchase_id`, nullable `supplier_id`,
`purchase_date`, and nullable `total_amount`. Existing sales columns are
`sale_id`, nullable `customer_id`, `sale_date`, and nullable `total_amount`.
Their only declared relations are to suppliers and customers respectively.
There is no current purchase/sale-to-vehicle relationship, item table,
inventory state, payment relation, or transaction status.

The live database does not identify acquisition provenance for the 41 current
vehicles. Do not infer purchases from `ownership_records`, `created_at`, or
vehicle ownership. Existing schema details are documented in
[DATABASE_ARCHITECTURE.md](./DATABASE_ARCHITECTURE.md), and the unchanged
current-schema diagram remains [ER_DIAGRAM.md](./ER_DIAGRAM.md).

## 2. Proposed schema extensions

The drafts are additive and deliberately avoid copying vehicle identity:

1. Add nullable `purchase_reference`, `purchase_status`, and `received_at`
   fields to the existing `purchases` header. Create `purchase_items` with one
   row per vehicle and its acquisition price/condition snapshot.
2. Add nullable `sale_reference` and `sale_status` fields to `sales`. Create
   `sale_items` with per-vehicle sale price, discount, tax, and generated line
   total.
3. Create `vehicle_inventory`, keyed by and FK-referencing `vehicles.vehicle_id`,
   for one current stock status, condition, and optional asking price per
   explicitly onboarded vehicle.
4. Create `payments`, with explicit purchase and sale FKs, payment lifecycle,
   event kind, and optional self-reference for a refund.
5. Add workflow triggers for purchase receipt, sale reservation/completion/
   cancellation, draft-line rules, and audit coverage. These are new functions
   and triggers; they do not replace the existing audit function or triggers.

No values are backfilled into existing headers or vehicles. Header extensions
are nullable so the draft does not guess the meaning of any pre-existing row
if data is added before a future approved migration. New application routes
must require references and valid statuses for new transactions.

## 3. Purchase management

`purchases` remains the transaction header and retains its current
`supplier_id`, `purchase_date`, and `total_amount` columns. The proposed
reference is unique when present; `purchase_status` is constrained to
`DRAFT`, `ORDERED`, `RECEIVED`, or `CANCELLED`. `received_at` captures the
inventory-entry event separately from the existing purchase date.

`purchase_items` contains an identity PK, required purchase and vehicle FKs,
nonnegative `purchase_price NUMERIC(12,2)`, and `condition_at_purchase`.
`UNIQUE (purchase_id, vehicle_id)` prohibits duplicate vehicle lines in one
header but allows later reacquisition on another purchase. FKs use
`ON DELETE RESTRICT`. A received purchase must have at least one line and a
supplier. New purchases begin as drafts; ordering also requires a nonblank
reference. Receipt creates a current inventory row for a vehicle not
previously tracked, or reopens a currently `SOLD` vehicle for an explicitly
recorded reacquisition. Receipt is rejected if the vehicle is currently
available, reserved, or under maintenance.

Purchase total remains in the existing header for compatibility. The
transaction service must calculate it from item prices and update the header
within the same transaction. Do not accept an unrelated caller total. Legacy
purchase rows, if any appear before migration, must be reviewed rather than
assigned guessed statuses or lines.

## 4. Sales management

`sales` retains its existing customer/date/total columns and gains nullable
reference/status extensions. `sale_items` contains one row per vehicle, the
sale header FK, sale price, nonnegative discount and tax amounts, and a stored
generated `line_total = selling_price - discount_amount + tax_amount`.
Constraints prevent negative values and discounts exceeding selling price.
`UNIQUE (sale_id, vehicle_id)` stops duplicate lines within one transaction
without globally forbidding future resale.

The proposed statuses are `DRAFT`, `CONFIRMED`, `COMPLETED`, and `CANCELLED`.
New sales begin as drafts; confirmation requires a customer, nonblank
reference, and at least one line. Only draft sales accept item inserts/deletes.
Adding a line locks the
corresponding vehicle/inventory row and reserves it for that sale. Confirmation
requires at least one line; completion moves all its reserved vehicles to
`SOLD` in the same transaction. Cancellation releases only reservations owned
by that sale. Sale detail rows are retained as history; correction is by
cancelling and creating a new draft rather than rewriting a completed sale.

The single `vehicle_inventory` row is the serialization point for competing
sales. Workflows must lock affected `vehicles` and inventory rows in ascending
`vehicle_id` order, check availability after acquiring the lock, and transition
state in the same database transaction. A second simultaneous sale waits for
the lock and then fails because the vehicle is no longer available. This
avoids an incorrect global unique constraint on `sale_items.vehicle_id`, which
would prohibit legitimate resales. All writers must use the approved
transaction path; direct unrestricted SQL updates to inventory would bypass
workflow guarantees.

Per-item prices are financial snapshots. Existing `sales.total_amount` is
maintained transactionally from line totals. The generated total protects each
line only; a child-row sum cannot be enforced with an ordinary row-level CHECK.
The API/transaction function and tests must validate header totals.

## 5. Payment design

A separate payment-event table is appropriate because a purchase or sale may
be paid in installments, have pending/failed/voided attempts, or receive
refunds. `payments` has a required unique `payment_reference`, positive amount,
timestamp, method, and `payment_status` (`PENDING`, `COMPLETED`, `FAILED`,
`VOIDED`). `payment_kind` distinguishes `PAYMENT` from `REFUND`; a refund must
reference an original payment. `purchase_id` and `sale_id` are independently
nullable FKs with an exactly-one-parent check. All transaction FKs, including
the self-FK, use restrictive deletes.

The payment status of a purchase or sale should be **derived**, not stored as
another potentially inconsistent header field: aggregate completed payment
events minus completed refunds against the transaction total. Pending,
failed, and voided events do not count as settled funds. Enforce that a refund
references an event for the same transaction and does not exceed the
unrefunded amount in the payment transaction/API; those are cross-row
invariants and cannot be expressed as a simple CHECK. The approved Phase 5
currency is PKR. The initial Phase 5 backend does not expose tax and accepts
only zero tax; the draft constraint should match this rule until a separate tax
design is approved.

## 6. Inventory status and lifecycle

The proposed statuses are `AVAILABLE`, `RESERVED`, `SOLD`, and
`UNDER_MAINTENANCE`. The table also stores current condition and optional
`asking_price`; it does not duplicate VIN, registration number, make/model, or
other attributes already held by `vehicles`.

| Event | Proposed current-state effect |
|---|---|
| Explicit stock onboarding or purchase receipt | Create an `AVAILABLE` row. Do not auto-classify all legacy vehicles. |
| Add a vehicle to a draft sale | Lock and change `AVAILABLE` to `RESERVED`, linked to that sale. |
| Complete a confirmed sale | Change that sale's reservations to `SOLD` and record the latest sale ID. |
| Cancel a draft/confirmed sale | Release only that sale's `RESERVED` rows back to `AVAILABLE`. |
| Receive a later purchase of a sold vehicle | Record a new purchase line and transition `SOLD` to `AVAILABLE`; historical sale/purchase lines remain. |
| Maintenance | An authorized workflow may move available stock to `UNDER_MAINTENANCE`; it cannot be reserved until returned to `AVAILABLE`. |

The status/FK check requires reservation linkage only while reserved and latest
sale linkage only while sold. `status_changed_at` and `updated_at` record
current-state changes. Inventory valuation should be reported by joining stock
to the most recent received purchase line for its current acquisition cost;
asking price is a listing value, not an accounting cost. Legacy vehicles with
no evidenced acquisition cost must show unknown cost, not zero. The initial
stock-onboarding path requires an evidence note/reference and does not create a
historical purchase record. Do not bulk-classify existing vehicles or invent
opening-balance values. Accounting treatment remains a business decision.

Purchases and sales remain separate from legal ownership history. The current
`customers` and `owners` tables have no relationship, and the schema does not
establish that a customer is an owner. Sale completion therefore must not
silently insert/update `ownership_records`. An explicit, separately approved
owner-mapping and transfer workflow should invoke the existing ownership
transfer process when required.

## 7. Proposed constraints and indexes

| Proposed object | Keys, nullability, checks/defaults | Index and integrity purpose |
|---|---|---|
| `purchases` additions | Nullable unique reference and nullable checked status/receipt timestamp on the existing header; no default/backfill for legacy rows. | Partial unique reference index supports lookup without rejecting legacy NULLs; status/date index supports work queues. |
| `purchase_items` | Identity integer PK; purchase and vehicle FKs NOT NULL; price NUMERIC(12,2) NOT NULL and `>= 0`; condition snapshot NOT NULL/default `UNKNOWN`; unique `(purchase_id, vehicle_id)`. | Unique header/vehicle index supports purchase detail; vehicle-leading index supports acquisition history. |
| `sales` additions | Nullable unique reference and nullable checked status on existing header; no default/backfill for legacy rows. | Partial unique reference and status/date work-queue indexes. |
| `sale_items` | Identity integer PK; sale and vehicle FKs NOT NULL; prices/discount/tax NOT NULL; prices/discount nonnegative, discount no more than price, tax exactly zero for the approved initial policy; generated line total; unique `(sale_id, vehicle_id)`. | Unique header/vehicle index supports sale detail; vehicle-leading index supports sale history. |
| `vehicle_inventory` | `vehicle_id` is both PK and restricted FK; required status/condition with defaults and checks; nonnegative nullable asking price; required nonblank onboarding evidence note; restricted nullable reservation/latest-sale FKs; status/link consistency check. | Status index supports stock filters; partial indexes on reservation and latest sale support workflow/history joins. |
| `payments` | Identity PK; unique required reference; exactly one restricted purchase/sale FK; positive amount; currency fixed to PKR; checked method, kind, and status; refund kind requires a restricted self-FK. | Partial indexes on purchase, sale, and refund parent support per-header history and balances. |

New FKs use `ON DELETE RESTRICT` so referenced vehicles, headers, and payment
events cannot be removed while transaction history depends on them. Header
party nullability and delete behavior are not tightened. Add indexes only for
demonstrated lookup/workflow paths; compare query plans before deployment.
Although the drafts use name guards and `IF NOT EXISTS`, these are not a
substitute for a schema-drift preflight: PostgreSQL does not verify that a
same-named pre-existing index/table has the intended definition.

## 8. Data integrity, audit, and compatibility

- Keep all existing tables, columns, views, and rows. No legacy vehicle
  purchase/sale events or stock states are synthesized.
- Preserve `vehicles` as the sole source for registration and vehicle identity.
- Keep current ownership history authoritative and separate from transaction
  history.
- Calculate totals from details in a single transaction; test every failure
  path for rollback of header, line, payment, stock, and audit effects.
- Row-lock vehicle identities and inventory states in consistent sorted order.
  Add concurrency tests for two simultaneous attempts to reserve the same
  vehicle and for purchase receipt racing a sale.
- Add audit triggers for proposed transaction/inventory changes through a new,
  Phase-4-specific function. Do not replace or redefine the live
  `audit_ledger_row_change()` function or existing triggers. The audit actor
  comes from the application's transaction-local `app.user_id`; null actors
  must remain possible for non-application database operations.
- Supplier/customer API writes should explicitly append audit rows until
  reviewed database audit triggers are approved for those existing tables.
- The proposed SQL leaves `purchases.supplier_id` and `sales.customer_id`
  nullable for compatibility. New API validation should require the relevant
  party for ordered purchases/completed business flow without changing legacy
  constraints.
- The existing frontend/backend currently have no customer, supplier,
  purchase, or sales modules/routes. The established application has vehicle
  and vehicle-history workflows plus authentication/role checks; no commerce
  endpoints, transaction authorization matrix, or corresponding UI is covered
  by this database design. The existing permission policy is application
  level, not PostgreSQL row-level security. Phase 5 must implement and test
  these surfaces before deployment.

## 9. Migration order (future, approval required)

No step below has been performed.

1. Use the approved Phase 5 settings: PKR, no tax initially, unpaid/partial
   sales allowed, customers separate from owners, and no inferred historical
   purchase or opening-stock records. Confirm remaining references, status
   transitions, payment/refund policy, and role permissions.
2. Recheck live schema and counts; review same-name object drift and any
   purchase/sale rows created since this snapshot.
3. Create a fresh verified backup and perform a restore drill into an isolated
   PostgreSQL 18 database.
4. Apply the reviewed additive DDL for header extensions and purchase/sale
   items (`001`, `002`) to the isolated copy.
5. Add `vehicle_inventory` and payment DDL (`003`, `004`), then workflow/audit
   triggers (`005`). The trigger draft requires all referenced proposed
   relations and fields to exist.
6. Add and test per-vehicle inventory onboarding with an evidence note; do not
   bulk-mark existing vehicles available or fabricate acquisition history.
7. Test constraints, trigger transitions, total reconciliation, payment
   refunds, audit actor capture, concurrency, and rollback on the restored
   copy. Compare existing row keys/counts and schema before/after.
8. Obtain approval for an execution window, take and verify a fresh backup,
   then apply only the reviewed draft-derived migration with fail-fast
   behavior. Do not run `db/reset_and_reseed.ps1` or existing seed scripts.
9. Run post-deployment checks and enable routes only after the schema and
   application tests pass.

## 10. Rollback strategy

Prefer disabling new routes and making a forward corrective migration while
retaining purchase, sale, payment, audit, and inventory history. Do not
automatically drop populated new tables or reverse transactions by deleting
their records. A rollback of application code should leave additive schema
objects intact. For catastrophic recovery, restore the verified archive to a
separate database, validate it, and perform any cutover only with explicit
approval. No destructive down migration is provided in this design phase; a
down-script could be considered only for an isolated test database after
proving all proposed objects are empty.

## 11. Risks and unresolved decisions

1. **Opening inventory:** the existing 41 vehicles have no confirmed purchase
   provenance in this schema. Individually onboard stock only with evidence;
   decide which vehicles are dealer stock, customer-owned, sold, or out of
   scope.
2. **Payment lifecycle:** confirm supported payment methods, provider states,
   refunds, and whether an unpaid/partially paid sale may be delivered.
3. **Status vocabulary:** confirm purchase and sale transitions and the
   complete permission matrix. Verification User remains denied.
4. **Inventory entry:** decide how non-purchase stock (trade-in, opening
   balance, donation) is evidenced.
5. **Accounting valuation:** confirm whether most recent purchase price is a
   sufficient cost basis or whether fees, repairs, and accounting adjustments
   are needed.
6. **Operational deployment:** current SQL helper runs legacy numbered SQL
   scripts, including a data-changing demo seed; it is not appropriate for
   these drafts. A versioned, reviewed migration runner and test restore
   process are needed.

## Deliverables

- Proposed ER diagram: [PHASE_4_PROPOSED_ER_DIAGRAM.md](./PHASE_4_PROPOSED_ER_DIAGRAM.md)
- SQL drafts:
  - [`001_purchase_design.sql`](../db/proposed_phase4/001_purchase_design.sql)
  - [`002_sales_design.sql`](../db/proposed_phase4/002_sales_design.sql)
  - [`003_vehicle_inventory_design.sql`](../db/proposed_phase4/003_vehicle_inventory_design.sql)
  - [`004_payments_design.sql`](../db/proposed_phase4/004_payments_design.sql)
  - [`005_lifecycle_and_audit_triggers_design.sql`](../db/proposed_phase4/005_lifecycle_and_audit_triggers_design.sql)
- Existing schema source: [DATABASE_ARCHITECTURE.md](./DATABASE_ARCHITECTURE.md)
