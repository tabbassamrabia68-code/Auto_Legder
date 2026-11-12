-- PROPOSED — NOT EXECUTED — FOUNDATION DESIGN ONLY.
-- This file is not deployable by itself. Backend tenant-context resolution,
-- per-business query filters, and tenant-aware lifecycle/audit triggers must
-- be implemented and tested before any production use.
-- Depends on the Phase 4 commerce tables and Phase 7 001_auth_business_extensions.sql.
-- Existing rows remain business_id NULL; this draft deliberately does not
-- guess which business owns existing customers, suppliers, transactions, or logs.

BEGIN;

DO $$
DECLARE
    required_table TEXT;
BEGIN
    FOREACH required_table IN ARRAY ARRAY[
        'public.users', 'public.roles', 'public.owners', 'public.vehicles',
        'public.suppliers', 'public.customers', 'public.purchases',
        'public.purchase_items', 'public.sales', 'public.sale_items',
        'public.vehicle_inventory', 'public.payments', 'public.audit_logs'
    ]
    LOOP
        IF to_regclass(required_table) IS NULL THEN
            RAISE EXCEPTION
                'Required Phase 4/7 relation % is missing; review migration order',
                required_table;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('Super Admin'), ('Admin'), ('Business Owner'), ('Manager'),
            ('Accountant'), ('Staff'), ('Viewer')
        ) expected(role_name)
        WHERE NOT EXISTS (
            SELECT 1 FROM public.roles r WHERE r.role_name = expected.role_name
        )
    ) THEN
        RAISE EXCEPTION
            'The approved seven-role catalog is incomplete; apply no tenant changes';
    END IF;
END
$$;

-- A business is a tenant boundary. A duplicate display name is allowed because
-- separate legal businesses may share a trading name.
CREATE TABLE IF NOT EXISTS public.businesses (
    business_id INTEGER GENERATED ALWAYS AS IDENTITY,
    business_name VARCHAR(160) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_businesses_p7 PRIMARY KEY (business_id),
    CONSTRAINT ck_businesses_p7_name CHECK (BTRIM(business_name) <> '')
);

-- A user may join multiple businesses, with one active role per business.
-- Existing global user.role_id assignments are not changed by this table.
CREATE TABLE IF NOT EXISTS public.business_memberships (
    user_id INTEGER NOT NULL,
    business_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_business_memberships_p7 PRIMARY KEY (user_id, business_id),
    CONSTRAINT fk_business_memberships_p7_user
        FOREIGN KEY (user_id) REFERENCES public.users (user_id) ON DELETE RESTRICT,
    CONSTRAINT fk_business_memberships_p7_business
        FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT,
    CONSTRAINT fk_business_memberships_p7_role
        FOREIGN KEY (role_id) REFERENCES public.roles (role_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_business_memberships_p7_business
    ON public.business_memberships (business_id, user_id);
CREATE INDEX IF NOT EXISTS ix_business_memberships_p7_role
    ON public.business_memberships (role_id);

-- The nullable tenant keys preserve all current, unmapped business records.
-- New application writes must provide a tenant after tenant-aware APIs exist.
ALTER TABLE public.suppliers
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.purchases
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.purchase_items
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.sales
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.sale_items
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.vehicle_inventory
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.payments
    ADD COLUMN IF NOT EXISTS business_id INTEGER;
ALTER TABLE public.audit_logs
    ADD COLUMN IF NOT EXISTS business_id INTEGER;

-- Composite unique indexes support tenant-matching foreign keys below.
-- Existing primary keys remain unchanged.
CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_p7_id_business
    ON public.suppliers (supplier_id, business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_p7_id_business
    ON public.customers (customer_id, business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_p7_id_business
    ON public.purchases (purchase_id, business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_p7_id_business
    ON public.sales (sale_id, business_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vehicle_inventory_p7_vehicle_business
    ON public.vehicle_inventory (vehicle_id, business_id);

-- Add tenant foreign keys only when the specifically named constraint is absent.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.suppliers'::regclass AND conname='fk_suppliers_p7_business') THEN
        ALTER TABLE public.suppliers ADD CONSTRAINT fk_suppliers_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.customers'::regclass AND conname='fk_customers_p7_business') THEN
        ALTER TABLE public.customers ADD CONSTRAINT fk_customers_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.purchases'::regclass AND conname='fk_purchases_p7_business') THEN
        ALTER TABLE public.purchases ADD CONSTRAINT fk_purchases_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.purchases'::regclass AND conname='fk_purchases_p7_supplier_tenant') THEN
        ALTER TABLE public.purchases ADD CONSTRAINT fk_purchases_p7_supplier_tenant
            FOREIGN KEY (supplier_id, business_id)
            REFERENCES public.suppliers (supplier_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.purchase_items'::regclass AND conname='fk_purchase_items_p7_tenant_header') THEN
        ALTER TABLE public.purchase_items ADD CONSTRAINT fk_purchase_items_p7_tenant_header
            FOREIGN KEY (purchase_id, business_id)
            REFERENCES public.purchases (purchase_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.sales'::regclass AND conname='fk_sales_p7_business') THEN
        ALTER TABLE public.sales ADD CONSTRAINT fk_sales_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.sales'::regclass AND conname='fk_sales_p7_customer_tenant') THEN
        ALTER TABLE public.sales ADD CONSTRAINT fk_sales_p7_customer_tenant
            FOREIGN KEY (customer_id, business_id)
            REFERENCES public.customers (customer_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.sale_items'::regclass AND conname='fk_sale_items_p7_tenant_header') THEN
        ALTER TABLE public.sale_items ADD CONSTRAINT fk_sale_items_p7_tenant_header
            FOREIGN KEY (sale_id, business_id)
            REFERENCES public.sales (sale_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.sale_items'::regclass AND conname='fk_sale_items_p7_tenant_inventory') THEN
        ALTER TABLE public.sale_items ADD CONSTRAINT fk_sale_items_p7_tenant_inventory
            FOREIGN KEY (vehicle_id, business_id)
            REFERENCES public.vehicle_inventory (vehicle_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.vehicle_inventory'::regclass AND conname='fk_vehicle_inventory_p7_business') THEN
        ALTER TABLE public.vehicle_inventory ADD CONSTRAINT fk_vehicle_inventory_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.payments'::regclass AND conname='fk_payments_p7_business') THEN
        ALTER TABLE public.payments ADD CONSTRAINT fk_payments_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.payments'::regclass AND conname='fk_payments_p7_purchase_tenant') THEN
        ALTER TABLE public.payments ADD CONSTRAINT fk_payments_p7_purchase_tenant
            FOREIGN KEY (purchase_id, business_id)
            REFERENCES public.purchases (purchase_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.payments'::regclass AND conname='fk_payments_p7_sale_tenant') THEN
        ALTER TABLE public.payments ADD CONSTRAINT fk_payments_p7_sale_tenant
            FOREIGN KEY (sale_id, business_id)
            REFERENCES public.sales (sale_id, business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.audit_logs'::regclass AND conname='fk_audit_logs_p7_business') THEN
        ALTER TABLE public.audit_logs ADD CONSTRAINT fk_audit_logs_p7_business
            FOREIGN KEY (business_id) REFERENCES public.businesses (business_id) ON DELETE RESTRICT NOT VALID;
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.phase7_membership_role_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_role_name TEXT;
BEGIN
    SELECT role_name INTO v_role_name
    FROM public.roles
    WHERE role_id = NEW.role_id;

    IF v_role_name IS NULL OR v_role_name NOT IN (
        'Super Admin', 'Admin', 'Business Owner', 'Manager',
        'Accountant', 'Staff', 'Viewer'
    ) THEN
        RAISE EXCEPTION 'Business membership requires one of the approved active roles';
    END IF;

    RETURN NEW;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'public.business_memberships'::regclass
          AND tgname = 'trg_p7_membership_role_guard'
          AND NOT tgisinternal
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_p7_membership_role_guard
            BEFORE INSERT OR UPDATE OF role_id
            ON public.business_memberships
            FOR EACH ROW
            EXECUTE FUNCTION public.phase7_membership_role_guard()';
    END IF;
END
$$;

-- Tenant-leading indexes support explicit business filters in future queries.
CREATE INDEX IF NOT EXISTS ix_suppliers_p7_business
    ON public.suppliers (business_id, supplier_id) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_customers_p7_business
    ON public.customers (business_id, customer_id) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_purchases_p7_business_date
    ON public.purchases (business_id, purchase_date DESC) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_purchase_items_p7_business
    ON public.purchase_items (business_id, purchase_id) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_sales_p7_business_date
    ON public.sales (business_id, sale_date DESC) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_sale_items_p7_business
    ON public.sale_items (business_id, sale_id) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_vehicle_inventory_p7_business_status
    ON public.vehicle_inventory (business_id, stock_status) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_payments_p7_business_date
    ON public.payments (business_id, payment_date DESC) WHERE business_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_audit_logs_p7_business_date
    ON public.audit_logs (business_id, action_timestamp DESC) WHERE business_id IS NOT NULL;

COMMENT ON TABLE public.business_memberships IS
    'PROPOSED PHASE 7 design only; tenant-role membership, with no legacy user reassignment.';
COMMENT ON COLUMN public.audit_logs.business_id IS
    'PROPOSED tenant scope; existing audit rows remain NULL until explicitly mapped.';

COMMIT;

-- Required follow-up before use: implement membership-aware authorization,
-- tenant filters on every API/report/export, tenant-aware purchase/sale/payment
-- and inventory triggers, and a reviewed unassigned-data policy. Do not mark
-- these nullable columns NOT NULL until every existing row is deliberately
-- mapped and the application enforces business context on all writes.
