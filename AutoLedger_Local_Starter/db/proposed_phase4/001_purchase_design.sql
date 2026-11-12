-- PROPOSED — NOT EXECUTED
-- Phase 5-compatible purchase design draft.
-- Adds purchase workflow metadata and per-vehicle acquisition lines.
-- Review the live schema and same-name object definitions before any future use.
-- This draft is additive; rollback must not remove populated transaction history.

BEGIN;

-- Nullable additions preserve compatibility and do not invent values for
-- legacy purchase headers. New application writes should require both fields.
ALTER TABLE public.purchases
    ADD COLUMN IF NOT EXISTS purchase_reference VARCHAR(50),
    ADD COLUMN IF NOT EXISTS purchase_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.purchases'::regclass
          AND conname = 'ck_purchases_p4_status'
    ) THEN
        ALTER TABLE public.purchases
            ADD CONSTRAINT ck_purchases_p4_status
            CHECK (purchase_status IS NULL OR purchase_status IN
                ('DRAFT', 'ORDERED', 'RECEIVED', 'CANCELLED'));
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_p4_reference
    ON public.purchases (purchase_reference)
    WHERE purchase_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_purchases_p4_status_date
    ON public.purchases (purchase_status, purchase_date DESC);

CREATE TABLE IF NOT EXISTS public.purchase_items (
    purchase_item_id INTEGER GENERATED ALWAYS AS IDENTITY,
    purchase_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    purchase_price NUMERIC(12, 2) NOT NULL,
    condition_at_purchase VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    CONSTRAINT pk_purchase_items_p4 PRIMARY KEY (purchase_item_id)
);

-- Add constraints separately so rerunning an interrupted draft is guarded.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'pk_purchase_items_p4') THEN
        IF EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND contype = 'p') THEN
            RAISE EXCEPTION
                'purchase_items has an unexpected primary key; review schema drift';
        END IF;
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT pk_purchase_items_p4 PRIMARY KEY (purchase_item_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'fk_purchase_items_p4_purchase') THEN
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT fk_purchase_items_p4_purchase
            FOREIGN KEY (purchase_id) REFERENCES public.purchases (purchase_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'fk_purchase_items_p4_vehicle') THEN
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT fk_purchase_items_p4_vehicle
            FOREIGN KEY (vehicle_id) REFERENCES public.vehicles (vehicle_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'ck_purchase_items_p4_price') THEN
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT ck_purchase_items_p4_price
            CHECK (purchase_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'ck_purchase_items_p4_condition') THEN
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT ck_purchase_items_p4_condition
            CHECK (condition_at_purchase IN
                ('UNKNOWN', 'NEW', 'EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'DAMAGED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.purchase_items'::regclass
                     AND conname = 'uq_purchase_items_p4_purchase_vehicle') THEN
        ALTER TABLE public.purchase_items
            ADD CONSTRAINT uq_purchase_items_p4_purchase_vehicle
            UNIQUE (purchase_id, vehicle_id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_purchase_items_p4_vehicle
    ON public.purchase_items (vehicle_id, purchase_id);

COMMENT ON TABLE public.purchase_items IS
    'PROPOSED PHASE 4 design only; one vehicle per purchase line.';

COMMIT;

-- Rollback note: no automatic DROP is supplied. Retain populated purchase
-- history; consider removal only in a disposable test database after proving
-- the proposed objects are empty and approving a separate down migration.
