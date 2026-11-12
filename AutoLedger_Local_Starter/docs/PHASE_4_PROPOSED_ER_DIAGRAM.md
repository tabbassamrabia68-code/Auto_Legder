# AutoLedger Phase 4 Proposed ER Diagram

**Status:** Design only. No proposed object or change in this document has
been applied to PostgreSQL.

The existing entities and columns below were checked against the live
`autoledger_db` catalog on 2026-11-07 (PostgreSQL 18.6, schema `public`).
Existing fields are shown without a prefix. Fields marked **PROPOSED** are
new design fields and are not present in the live database. `PURCHASE_ITEMS`,
`SALE_ITEMS`, `VEHICLE_INVENTORY`, and `PAYMENTS` are proposed new tables.

```mermaid
erDiagram
    %% Existing relationships verified in the live catalog.
    ROLES ||--o{ USERS : "existing role_id"
    USERS o|--o{ AUDIT_LOGS : "existing nullable user_id"
    USERS ||--o{ INSPECTIONS : "existing inspector_id"
    USERS ||--o{ VERIFICATION_RECORDS : "existing verified_by"
    VEHICLES ||--o{ OWNERSHIP_RECORDS : "existing vehicle_id"
    OWNERS ||--o{ OWNERSHIP_RECORDS : "existing owner_id"
    VEHICLES ||--o{ SERVICE_RECORDS : "existing vehicle_id"
    VEHICLES ||--o{ REPAIR_RECORDS : "existing vehicle_id"
    VEHICLES ||--o{ MILEAGE_RECORDS : "existing vehicle_id"
    VEHICLES ||--o{ INSPECTIONS : "existing vehicle_id"
    VEHICLES ||--o{ DOCUMENTS : "existing vehicle_id"
    VEHICLES ||--o{ VERIFICATION_RECORDS : "existing vehicle_id"
    SUPPLIERS o|--o{ PURCHASES : "existing nullable supplier_id"
    CUSTOMERS o|--o{ SALES : "existing nullable customer_id"

    %% Proposed relationships. Transaction headers may be drafts with no items;
    %% confirmation/receipt/completion will require at least one item.
    PURCHASES ||--o{ PURCHASE_ITEMS : "proposed purchase_id"
    VEHICLES ||--o{ PURCHASE_ITEMS : "proposed vehicle_id; acquisition history"
    SALES ||--o{ SALE_ITEMS : "proposed sale_id"
    VEHICLES ||--o{ SALE_ITEMS : "proposed vehicle_id; sale history"
    VEHICLES ||--o| VEHICLE_INVENTORY : "proposed zero-or-one current stock row"
    SALES o|--o{ VEHICLE_INVENTORY : "proposed reserved_for_sale_id"
    SALES o|--o{ VEHICLE_INVENTORY : "proposed sold_sale_id"
    PURCHASES o|--o{ PAYMENTS : "proposed nullable purchase_id"
    SALES o|--o{ PAYMENTS : "proposed nullable sale_id"
    PAYMENTS o|--o{ PAYMENTS : "proposed reversal_of_payment_id"

    ROLES {
        int role_id PK "EXISTING"
        varchar role_name UK "EXISTING"
        varchar description "EXISTING"
    }
    USERS {
        int user_id PK "EXISTING"
        int role_id FK "EXISTING"
        varchar full_name "EXISTING"
        varchar email UK "EXISTING"
        varchar phone "EXISTING nullable"
        boolean is_active "EXISTING"
        timestamp created_at "EXISTING"
        varchar password_hash "EXISTING nullable"
    }
    AUDIT_LOGS {
        int audit_id PK "EXISTING"
        int user_id FK "EXISTING nullable"
        varchar action "EXISTING"
        varchar entity_name "EXISTING"
        int entity_id "EXISTING nullable"
        timestamp action_timestamp "EXISTING"
        text details "EXISTING nullable"
    }
    OWNERS {
        int owner_id PK "EXISTING"
        varchar full_name "EXISTING"
        varchar phone "EXISTING nullable"
        varchar email "EXISTING nullable"
        timestamp created_at "EXISTING"
    }
    VEHICLES {
        int vehicle_id PK "EXISTING"
        varchar vin UK "EXISTING"
        varchar registration_no UK "EXISTING"
        varchar brand "EXISTING"
        varchar model "EXISTING"
        int model_year "EXISTING"
        varchar color "EXISTING nullable"
        varchar fuel_type "EXISTING nullable"
        varchar transmission "EXISTING nullable"
        varchar engine_no UK "EXISTING nullable"
        timestamp created_at "EXISTING"
    }
    OWNERSHIP_RECORDS {
        int ownership_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        int owner_id FK "EXISTING"
        date start_date "EXISTING"
        date end_date "EXISTING nullable"
        varchar ownership_status "EXISTING"
    }
    SERVICE_RECORDS {
        int service_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        date service_date "EXISTING"
        varchar service_type "EXISTING"
        int mileage "EXISTING nullable"
        varchar workshop_name "EXISTING nullable"
        text notes "EXISTING nullable"
        numeric cost "EXISTING nullable"
    }
    REPAIR_RECORDS {
        int repair_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        date repair_date "EXISTING"
        varchar repair_type "EXISTING"
        text description "EXISTING nullable"
        numeric cost "EXISTING nullable"
        varchar workshop_name "EXISTING nullable"
    }
    MILEAGE_RECORDS {
        int mileage_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        date recorded_date "EXISTING"
        int mileage "EXISTING"
        varchar source "EXISTING"
    }
    INSPECTIONS {
        int inspection_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        int inspector_id FK "EXISTING"
        date inspection_date "EXISTING"
        varchar result "EXISTING"
        text remarks "EXISTING nullable"
    }
    DOCUMENTS {
        int document_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        varchar document_type "EXISTING"
        varchar document_number "EXISTING nullable"
        date issue_date "EXISTING nullable"
        date expiry_date "EXISTING nullable"
        varchar status "EXISTING"
    }
    VERIFICATION_RECORDS {
        int verification_id PK "EXISTING"
        int vehicle_id FK "EXISTING"
        int verified_by FK "EXISTING"
        date verification_date "EXISTING"
        varchar result "EXISTING"
        text remarks "EXISTING nullable"
    }
    SUPPLIERS {
        int supplier_id PK "EXISTING"
        varchar supplier_name "EXISTING"
        varchar phone "EXISTING nullable"
        varchar email "EXISTING nullable"
    }
    PURCHASES {
        int purchase_id PK "EXISTING"
        int supplier_id FK "EXISTING nullable"
        date purchase_date "EXISTING"
        numeric total_amount "EXISTING nullable"
        varchar purchase_reference UK "PROPOSED nullable until legacy review"
        varchar purchase_status "PROPOSED nullable until legacy review"
        timestamptz received_at "PROPOSED nullable"
    }
    CUSTOMERS {
        int customer_id PK "EXISTING"
        varchar customer_name "EXISTING"
        varchar phone "EXISTING nullable"
        varchar email "EXISTING nullable"
    }
    SALES {
        int sale_id PK "EXISTING"
        int customer_id FK "EXISTING nullable"
        date sale_date "EXISTING"
        numeric total_amount "EXISTING nullable"
        varchar sale_reference UK "PROPOSED nullable until legacy review"
        varchar sale_status "PROPOSED nullable until legacy review"
    }
    PURCHASE_ITEMS {
        int purchase_item_id PK "PROPOSED identity"
        int purchase_id FK "PROPOSED not null"
        int vehicle_id FK "PROPOSED not null"
        numeric purchase_price "PROPOSED not null"
        varchar condition_at_purchase "PROPOSED not null"
    }
    SALE_ITEMS {
        int sale_item_id PK "PROPOSED identity"
        int sale_id FK "PROPOSED not null"
        int vehicle_id FK "PROPOSED not null"
        numeric selling_price "PROPOSED not null"
        numeric discount_amount "PROPOSED not null"
        numeric tax_amount "PROPOSED not null"
        numeric line_total "PROPOSED generated"
    }
    VEHICLE_INVENTORY {
        int vehicle_id PK_FK "PROPOSED one current row per existing vehicle"
        varchar stock_status "PROPOSED not null"
        varchar vehicle_condition "PROPOSED not null"
        numeric asking_price "PROPOSED nullable"
        int reserved_for_sale_id FK "PROPOSED nullable"
        int sold_sale_id FK "PROPOSED nullable"
        varchar source_note "PROPOSED evidence required"
        varchar source_reference "PROPOSED nullable"
        timestamptz status_changed_at "PROPOSED not null"
        timestamptz updated_at "PROPOSED not null"
    }
    PAYMENTS {
        int payment_id PK "PROPOSED identity"
        varchar payment_reference UK "PROPOSED not null"
        int purchase_id FK "PROPOSED nullable; XOR with sale_id"
        int sale_id FK "PROPOSED nullable; XOR with purchase_id"
        numeric amount "PROPOSED positive"
        char currency "PROPOSED PKR only"
        varchar payment_kind "PROPOSED PAYMENT or REFUND"
        int reversal_of_payment_id FK "PROPOSED nullable"
        timestamptz payment_date "PROPOSED not null"
        varchar payment_method "PROPOSED not null"
        varchar payment_status "PROPOSED not null"
        varchar external_reference "PROPOSED nullable"
    }
```

## Relationship explanation

### Existing relationships

The first 14 relationship lines are the live schema's declared foreign keys.
They retain the optional supplier/customer references, the existing owner and
vehicle history, and the existing user/audit relations. In particular,
`ownership_records` remains the authoritative ownership history; it is not
replaced by purchase or sale details.

### Proposed relationships

- Each purchase header can hold zero or more draft lines; each line references
  exactly one existing vehicle. A received purchase must have at least one
  line. A vehicle may appear in multiple purchase events over time for
  reacquisition, but not twice on one purchase.
- Sales follow the same header/line pattern. A vehicle may appear in multiple
  historical sale events, but not twice on one sale. It cannot be reserved or
  sold by two simultaneous active transactions because its single current
  inventory row is locked and transitioned within the sale transaction.
- A vehicle has zero or one current `vehicle_inventory` row. Existing vehicles
  are not assigned an invented status by the design; a row is created only
  through an approved stock-onboarding or purchase-receipt workflow.
- A payment references exactly one purchase or sale. The two nullable FKs are
  protected by an XOR check. A refund points to an earlier payment; the
  application transaction must also verify that it reverses a payment for the
  same header and does not exceed the remaining refundable amount.
- Each inventory row can hold one current reservation sale and one latest sale
  reference. These are separate nullable relationships; only one row exists
  per vehicle, so they describe current state and not sale history.
- No relationship is proposed between `customers` and `owners`. Sale
  completion does not automatically create or change an ownership record.

See [PHASE_4_DATABASE_DESIGN.md](./PHASE_4_DATABASE_DESIGN.md) for the full
rules, constraints, migration order, and unresolved business decisions.
