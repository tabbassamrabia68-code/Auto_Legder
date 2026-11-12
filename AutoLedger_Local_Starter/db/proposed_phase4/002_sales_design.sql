-- PROPOSED — NOT EXECUTED
-- Phase 5-compatible sales design draft.
-- Adds sales workflow metadata and per-vehicle sale lines.
-- Review the live schema and same-name object definitions before any future use.

BEGIN;

-- Nullable additions preserve legacy headers without guessed references/status.
ALTER TABLE public.sales
    ADD COLUMN IF NOT EXISTS sale_reference VARCHAR(50),
    ADD COLUMN IF NOT EXISTS sale_status VARCHAR(20);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.sales'::regclass
          AND conname = 'ck_sales_p4_status'
    ) THEN
        ALTER TABLE public.sales
            ADD CONSTRAINT ck_sales_p4_status
            CHECK (sale_status IS NULL OR sale_status IN
                ('DRAFT', 'CONFIRMED', 'COMPLETED', 'CANCELLED'));
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_p4_reference
    ON public.sales (sale_reference)
    WHERE sale_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_sales_p4_status_date
    ON public.sales (sale_status, sale_date DESC);

CREATE TABLE IF NOT EXISTS public.sale_items (
    sale_item_id INTEGER GENERATED ALWAYS AS IDENTITY,
    sale_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    selling_price NUMERIC(12, 2) NOT NULL,
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    line_total NUMERIC(12, 2) GENERATED ALWAYS AS
        (selling_price - discount_amount + tax_amount) STORED,
    CONSTRAINT pk_sale_items_p4 PRIMARY KEY (sale_item_id)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'pk_sale_items_p4') THEN
        IF EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND contype = 'p') THEN
            RAISE EXCEPTION
                'sale_items has an unexpected primary key; review schema drift';
        END IF;
        ALTER TABLE public.sale_items
            ADD CONSTRAINT pk_sale_items_p4 PRIMARY KEY (sale_item_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'fk_sale_items_p4_sale') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT fk_sale_items_p4_sale
            FOREIGN KEY (sale_id) REFERENCES public.sales (sale_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'fk_sale_items_p4_vehicle') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT fk_sale_items_p4_vehicle
            FOREIGN KEY (vehicle_id) REFERENCES public.vehicles (vehicle_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'ck_sale_items_p4_selling_price') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT ck_sale_items_p4_selling_price
            CHECK (selling_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'ck_sale_items_p4_discount') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT ck_sale_items_p4_discount
            CHECK (discount_amount >= 0 AND discount_amount <= selling_price);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'ck_sale_items_p4_tax') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT ck_sale_items_p4_tax
            CHECK (tax_amount = 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.sale_items'::regclass
                     AND conname = 'uq_sale_items_p4_sale_vehicle') THEN
        ALTER TABLE public.sale_items
            ADD CONSTRAINT uq_sale_items_p4_sale_vehicle
            UNIQUE (sale_id, vehicle_id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_sale_items_p4_vehicle
    ON public.sale_items (vehicle_id, sale_id);

COMMENT ON TABLE public.sale_items IS
    'PROPOSED PHASE 4 design only; one vehicle per sale line.';

COMMIT;

-- Rollback note: no automatic DROP is supplied. Sale line history is financial
-- history and must not be discarded by an application rollback.
