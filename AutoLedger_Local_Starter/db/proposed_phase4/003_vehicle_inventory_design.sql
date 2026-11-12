-- PROPOSED — NOT EXECUTED
-- Phase 5-compatible inventory design draft.
-- Adds one current stock-state row per explicitly onboarded existing vehicle.
-- This does not assign statuses or create rows for current legacy vehicles.

BEGIN;

CREATE TABLE IF NOT EXISTS public.vehicle_inventory (
    vehicle_id INTEGER NOT NULL,
    stock_status VARCHAR(24) NOT NULL DEFAULT 'AVAILABLE',
    vehicle_condition VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    asking_price NUMERIC(12, 2),
    source_note VARCHAR(500) NOT NULL,
    source_reference VARCHAR(120),
    reserved_for_sale_id INTEGER,
    sold_sale_id INTEGER,
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_vehicle_inventory_p4 PRIMARY KEY (vehicle_id)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'pk_vehicle_inventory_p4') THEN
        IF EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND contype = 'p') THEN
            RAISE EXCEPTION
                'vehicle_inventory has an unexpected primary key; review schema drift';
        END IF;
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT pk_vehicle_inventory_p4 PRIMARY KEY (vehicle_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'fk_vehicle_inventory_p4_vehicle') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT fk_vehicle_inventory_p4_vehicle
            FOREIGN KEY (vehicle_id) REFERENCES public.vehicles (vehicle_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'fk_vehicle_inventory_p4_reserved_sale') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT fk_vehicle_inventory_p4_reserved_sale
            FOREIGN KEY (reserved_for_sale_id) REFERENCES public.sales (sale_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'fk_vehicle_inventory_p4_sold_sale') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT fk_vehicle_inventory_p4_sold_sale
            FOREIGN KEY (sold_sale_id) REFERENCES public.sales (sale_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'ck_vehicle_inventory_p4_status') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT ck_vehicle_inventory_p4_status
            CHECK (stock_status IN
                ('AVAILABLE', 'RESERVED', 'SOLD', 'UNDER_MAINTENANCE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'ck_vehicle_inventory_p4_condition') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT ck_vehicle_inventory_p4_condition
            CHECK (vehicle_condition IN
                ('UNKNOWN', 'NEW', 'EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'DAMAGED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'ck_vehicle_inventory_p4_asking_price') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT ck_vehicle_inventory_p4_asking_price
            CHECK (asking_price IS NULL OR asking_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'ck_vehicle_inventory_p4_source_note') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT ck_vehicle_inventory_p4_source_note
            CHECK (BTRIM(source_note) <> '');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.vehicle_inventory'::regclass
                     AND conname = 'ck_vehicle_inventory_p4_sale_links') THEN
        ALTER TABLE public.vehicle_inventory
            ADD CONSTRAINT ck_vehicle_inventory_p4_sale_links
            CHECK (
                (stock_status = 'RESERVED'
                 AND reserved_for_sale_id IS NOT NULL
                 AND sold_sale_id IS NULL)
                OR
                (stock_status = 'SOLD'
                 AND reserved_for_sale_id IS NULL
                 AND sold_sale_id IS NOT NULL)
                OR
                (stock_status IN ('AVAILABLE', 'UNDER_MAINTENANCE')
                 AND reserved_for_sale_id IS NULL
                 AND sold_sale_id IS NULL)
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_vehicle_inventory_p4_status
    ON public.vehicle_inventory (stock_status, vehicle_id);

CREATE INDEX IF NOT EXISTS ix_vehicle_inventory_p4_reservation
    ON public.vehicle_inventory (reserved_for_sale_id)
    WHERE reserved_for_sale_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_vehicle_inventory_p4_latest_sale
    ON public.vehicle_inventory (sold_sale_id)
    WHERE sold_sale_id IS NOT NULL;

COMMENT ON TABLE public.vehicle_inventory IS
    'PROPOSED PHASE 4 design only; one current row per explicitly stocked vehicle.';

COMMIT;

-- Rollback note: do not remove current stock state or transaction links after
-- use. Any later rollback should disable routes and retain the additive table.
