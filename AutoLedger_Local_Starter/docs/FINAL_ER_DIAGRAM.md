# AutoLedger Entity Relationship Diagrams

The diagrams intentionally separate the **live schema** from the **proposed,
unexecuted design**. A proposed relation shown below is not present in the
live database.

## Current live relationships

Catalog inspected read-only on 2026-11-09. Current purchase/sale headers do
not point to vehicles; no purchase items, sale items, inventory, payments, or
businesses are installed.

```mermaid
erDiagram
    ROLES ||--o{ USERS : assigns
    USERS o|--o{ AUDIT_LOGS : acts_in
    VEHICLES ||--o{ OWNERSHIP_RECORDS : ownership_history
    OWNERS ||--o{ OWNERSHIP_RECORDS : owns
    VEHICLES ||--o{ SERVICE_RECORDS : serviced
    VEHICLES ||--o{ REPAIR_RECORDS : repaired
    VEHICLES ||--o{ MILEAGE_RECORDS : mileage
    VEHICLES ||--o{ INSPECTIONS : inspected
    USERS ||--o{ INSPECTIONS : inspector
    VEHICLES ||--o{ DOCUMENTS : documented
    VEHICLES ||--o{ VERIFICATION_RECORDS : verified
    USERS ||--o{ VERIFICATION_RECORDS : verifier
    SUPPLIERS o|--o{ PURCHASES : supplied
    CUSTOMERS o|--o{ SALES : customer
```

The four live views are `vw_vehicle_summary`, `vw_owner_history`,
`vw_expiring_documents`, and `vw_monthly_costs`. See
[ER_DIAGRAM.md](./ER_DIAGRAM.md) for the existing detailed diagram.

## Proposed future relationships — not live

The following captures the intended additive model in the Phase 4/7 drafts.
Tenant fields remain nullable so existing business rows can stay unassigned.
Application membership validation, per-query tenant filtering, and
tenant-aware triggers are required in addition to these FKs.

```mermaid
erDiagram
    USERS ||--o{ BUSINESS_MEMBERSHIPS : joins
    BUSINESSES ||--o{ BUSINESS_MEMBERSHIPS : has
    ROLES ||--o{ BUSINESS_MEMBERSHIPS : grants_role

    VEHICLES ||--o| VEHICLE_INVENTORY : stocked_as
    BUSINESSES ||--o{ VEHICLE_INVENTORY : owns_stock

    BUSINESSES ||--o{ SUPPLIERS : has
    BUSINESSES ||--o{ CUSTOMERS : has
    SUPPLIERS o|--o{ PURCHASES : supplier
    BUSINESSES ||--o{ PURCHASES : records
    PURCHASES ||--|{ PURCHASE_ITEMS : contains
    VEHICLES ||--o{ PURCHASE_ITEMS : purchased_vehicle

    CUSTOMERS o|--o{ SALES : customer
    BUSINESSES ||--o{ SALES : records
    SALES ||--|{ SALE_ITEMS : contains
    VEHICLES ||--o{ SALE_ITEMS : sold_vehicle

    PURCHASES o|--o{ PAYMENTS : purchase_payment
    SALES o|--o{ PAYMENTS : sale_payment
    BUSINESSES ||--o{ PAYMENTS : records
    PAYMENTS o|--o{ PAYMENTS : reverses
    BUSINESSES o|--o{ AUDIT_LOGS : scopes
```

`VEHICLE_INVENTORY` is proposed as one current stock row per vehicle, so the
model assumes a vehicle is stocked by at most one business at a time.
Concurrent sale prevention is based on locking and stock lifecycle checks,
not on a permanent unique `sale_items.vehicle_id` constraint, because later
resale must remain possible.

The current SQL draft should be independently reviewed for cross-tenant
consistency, especially purchase item and inventory onboarding order,
business-to-business vehicle transfer handling, and audit attribution. Do not
execute this diagram or the associated SQL against the live database.
