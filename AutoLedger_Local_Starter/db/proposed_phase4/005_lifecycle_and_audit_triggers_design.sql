-- PROPOSED — NOT EXECUTED
-- Phase 5-compatible lifecycle and audit triggers design draft.
-- Depends on proposed objects from 001_purchase_design.sql through
-- 004_payments_design.sql. Adds workflow and audit triggers without replacing
-- the existing audit function or its triggers.
-- Test this complete set on an isolated PostgreSQL 18 restore before approval.

BEGIN;

CREATE OR REPLACE FUNCTION public.phase4_purchase_item_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
    v_purchase_id INTEGER;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.purchase_id IS DISTINCT FROM OLD.purchase_id
           OR NEW.vehicle_id IS DISTINCT FROM OLD.vehicle_id THEN
            RAISE EXCEPTION
                'Purchase line identity is immutable; remove and recreate it while the purchase is a DRAFT';
        END IF;
    END IF;

    v_purchase_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.purchase_id
                          ELSE NEW.purchase_id END;

    SELECT purchase_status INTO v_status
    FROM public.purchases
    WHERE purchase_id = v_purchase_id
    FOR UPDATE;

    IF NOT FOUND OR v_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'Purchase items may only be changed on a DRAFT purchase';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_purchase_status_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_line_count BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.purchase_status IS NOT NULL
           AND NEW.purchase_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'A new purchase must start as DRAFT';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.purchase_status IS NOT DISTINCT FROM NEW.purchase_status THEN
        RETURN NEW;
    END IF;

    IF OLD.purchase_status IS NULL AND NEW.purchase_status = 'DRAFT' THEN
        RETURN NEW;
    ELSIF OLD.purchase_status = 'DRAFT'
          AND NEW.purchase_status IN ('ORDERED', 'CANCELLED') THEN
        IF NEW.purchase_status = 'ORDERED' THEN
            IF NEW.supplier_id IS NULL THEN
                RAISE EXCEPTION 'An ordered purchase requires a supplier';
            END IF;
            IF NULLIF(BTRIM(NEW.purchase_reference), '') IS NULL THEN
                RAISE EXCEPTION 'An ordered purchase requires a reference';
            END IF;
            SELECT COUNT(*) INTO v_line_count
            FROM public.purchase_items WHERE purchase_id = NEW.purchase_id;
            IF v_line_count = 0 THEN
                RAISE EXCEPTION 'An ordered purchase requires at least one vehicle';
            END IF;
        END IF;
        RETURN NEW;
    ELSIF OLD.purchase_status = 'ORDERED'
          AND NEW.purchase_status IN ('RECEIVED', 'CANCELLED') THEN
        IF NEW.purchase_status = 'RECEIVED' THEN
            SELECT COUNT(*) INTO v_line_count
            FROM public.purchase_items WHERE purchase_id = NEW.purchase_id;
            IF v_line_count = 0 THEN
                RAISE EXCEPTION 'A received purchase requires at least one vehicle';
            END IF;
            NEW.received_at := COALESCE(NEW.received_at, CURRENT_TIMESTAMP);
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'Invalid purchase status transition: % -> %',
        OLD.purchase_status, NEW.purchase_status;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_receive_purchase_inventory()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_line RECORD;
    v_status TEXT;
BEGIN
    IF NEW.purchase_status IS DISTINCT FROM 'RECEIVED'
       OR OLD.purchase_status IS NOT DISTINCT FROM NEW.purchase_status THEN
        RETURN NEW;
    END IF;

    FOR v_line IN
        SELECT vehicle_id, condition_at_purchase
        FROM public.purchase_items
        WHERE purchase_id = NEW.purchase_id
        ORDER BY vehicle_id
    LOOP
        -- All acquisition/sale paths lock the vehicle first, in ID order.
        PERFORM 1 FROM public.vehicles
        WHERE vehicle_id = v_line.vehicle_id
        FOR UPDATE;

        SELECT stock_status INTO v_status
        FROM public.vehicle_inventory
        WHERE vehicle_id = v_line.vehicle_id
        FOR UPDATE;

        IF NOT FOUND THEN
            INSERT INTO public.vehicle_inventory
                (vehicle_id, stock_status, vehicle_condition,
                 source_note, source_reference, status_changed_at, updated_at)
            VALUES
                (v_line.vehicle_id, 'AVAILABLE', v_line.condition_at_purchase,
                 'Received on purchase ' || NEW.purchase_reference,
                 NEW.purchase_reference,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        ELSIF v_status = 'SOLD' THEN
            UPDATE public.vehicle_inventory
            SET stock_status = 'AVAILABLE',
                vehicle_condition = v_line.condition_at_purchase,
                source_note = 'Reacquired on purchase ' || NEW.purchase_reference,
                source_reference = NEW.purchase_reference,
                reserved_for_sale_id = NULL,
                sold_sale_id = NULL,
                status_changed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE vehicle_id = v_line.vehicle_id;
        ELSE
            RAISE EXCEPTION
                'Vehicle % cannot be received while inventory status is %',
                v_line.vehicle_id, v_status;
        END IF;
    END LOOP;

    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_sale_item_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale_status TEXT;
    v_stock_status TEXT;
    v_reserved_sale_id INTEGER;
    v_sale_id INTEGER;
    v_vehicle_id INTEGER;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'Sale lines are immutable; correct a draft by deleting and re-adding the line';
    END IF;

    v_sale_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.sale_id ELSE NEW.sale_id END;
    v_vehicle_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.vehicle_id ELSE NEW.vehicle_id END;

    SELECT sale_status INTO v_sale_status
    FROM public.sales
    WHERE sale_id = v_sale_id
    FOR UPDATE;

    IF NOT FOUND OR v_sale_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'Sale lines may only be changed on a DRAFT sale';
    END IF;

    IF TG_OP = 'DELETE' THEN
        PERFORM 1 FROM public.vehicles
        WHERE vehicle_id = v_vehicle_id
        FOR UPDATE;

        UPDATE public.vehicle_inventory
        SET stock_status = 'AVAILABLE',
            reserved_for_sale_id = NULL,
            status_changed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE vehicle_id = v_vehicle_id
          AND stock_status = 'RESERVED'
          AND reserved_for_sale_id = v_sale_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Draft sale line has no matching vehicle reservation';
        END IF;
        RETURN OLD;
    END IF;

    PERFORM 1 FROM public.vehicles
    WHERE vehicle_id = NEW.vehicle_id
    FOR UPDATE;

    SELECT stock_status, reserved_for_sale_id
    INTO v_stock_status, v_reserved_sale_id
    FROM public.vehicle_inventory
    WHERE vehicle_id = NEW.vehicle_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Vehicle % has no inventory row; onboard it through an approved workflow first',
            NEW.vehicle_id;
    ELSIF v_stock_status = 'AVAILABLE' THEN
        UPDATE public.vehicle_inventory
        SET stock_status = 'RESERVED',
            reserved_for_sale_id = NEW.sale_id,
            status_changed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE vehicle_id = NEW.vehicle_id;
    ELSIF v_stock_status = 'RESERVED'
          AND v_reserved_sale_id = NEW.sale_id THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'Vehicle % is not available for sale (status %)',
            NEW.vehicle_id, v_stock_status;
    END IF;

    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_sale_status_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_line_count BIGINT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.sale_status IS NOT NULL
           AND NEW.sale_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'A new sale must start as DRAFT';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.sale_status IS NOT DISTINCT FROM NEW.sale_status THEN
        RETURN NEW;
    END IF;

    IF OLD.sale_status IS NULL AND NEW.sale_status = 'DRAFT' THEN
        RETURN NEW;
    ELSIF OLD.sale_status = 'DRAFT'
          AND NEW.sale_status IN ('CONFIRMED', 'CANCELLED') THEN
        IF NEW.sale_status = 'CONFIRMED' THEN
            IF NEW.customer_id IS NULL THEN
                RAISE EXCEPTION 'A confirmed sale requires a customer';
            END IF;
            IF NULLIF(BTRIM(NEW.sale_reference), '') IS NULL THEN
                RAISE EXCEPTION 'A confirmed sale requires a reference';
            END IF;
            SELECT COUNT(*) INTO v_line_count
            FROM public.sale_items WHERE sale_id = NEW.sale_id;
            IF v_line_count = 0 THEN
                RAISE EXCEPTION 'A confirmed sale requires at least one vehicle';
            END IF;
        END IF;
        RETURN NEW;
    ELSIF OLD.sale_status = 'CONFIRMED'
          AND NEW.sale_status IN ('COMPLETED', 'CANCELLED') THEN
        IF NEW.sale_status = 'COMPLETED' THEN
            SELECT COUNT(*) INTO v_line_count
            FROM public.sale_items WHERE sale_id = NEW.sale_id;
            IF v_line_count = 0 THEN
                RAISE EXCEPTION 'A completed sale requires at least one vehicle';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'Invalid sale status transition: % -> %',
        OLD.sale_status, NEW.sale_status;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_apply_sale_inventory()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_line_count BIGINT;
    v_changed BIGINT;
BEGIN
    IF OLD.sale_status IS NOT DISTINCT FROM NEW.sale_status THEN
        RETURN NEW;
    END IF;

    IF NEW.sale_status = 'COMPLETED' THEN
        SELECT COUNT(*) INTO v_line_count
        FROM public.sale_items WHERE sale_id = NEW.sale_id;

        UPDATE public.vehicle_inventory
        SET stock_status = 'SOLD',
            reserved_for_sale_id = NULL,
            sold_sale_id = NEW.sale_id,
            status_changed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE stock_status = 'RESERVED'
          AND reserved_for_sale_id = NEW.sale_id;
        GET DIAGNOSTICS v_changed = ROW_COUNT;

        IF v_line_count = 0 OR v_changed <> v_line_count THEN
            RAISE EXCEPTION
                'Sale completion requires a matching reservation for every sale line';
        END IF;
    ELSIF NEW.sale_status = 'CANCELLED' THEN
        UPDATE public.vehicle_inventory
        SET stock_status = 'AVAILABLE',
            reserved_for_sale_id = NULL,
            status_changed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE stock_status = 'RESERVED'
          AND reserved_for_sale_id = NEW.sale_id;
    END IF;

    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION public.phase4_audit_commerce_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_before JSONB;
    v_after JSONB;
    v_row JSONB;
    v_entity_id INTEGER;
    v_actor_id INTEGER;
    v_action TEXT := TG_OP;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_after := to_jsonb(NEW);
        v_row := v_after;
    ELSIF TG_OP = 'UPDATE' THEN
        v_before := to_jsonb(OLD);
        v_after := to_jsonb(NEW);
        v_row := v_after;
    ELSE
        v_before := to_jsonb(OLD);
        v_row := v_before;
    END IF;

    v_entity_id := (v_row ->> CASE TG_TABLE_NAME
        WHEN 'purchases' THEN 'purchase_id'
        WHEN 'purchase_items' THEN 'purchase_item_id'
        WHEN 'sales' THEN 'sale_id'
        WHEN 'sale_items' THEN 'sale_item_id'
        WHEN 'vehicle_inventory' THEN 'vehicle_id'
        WHEN 'payments' THEN 'payment_id'
        ELSE NULL
    END)::INTEGER;

    v_actor_id := NULLIF(current_setting('app.user_id', true), '')::INTEGER;

    INSERT INTO public.audit_logs
        (user_id, action, entity_name, entity_id, details)
    VALUES
        (v_actor_id, v_action, TG_TABLE_NAME, v_entity_id,
         jsonb_build_object('before', v_before, 'after', v_after)::TEXT);

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;

-- Add each trigger only if its specifically named trigger is absent.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.purchase_items'::regclass
                     AND tgname = 'trg_p4_purchase_item_guard'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_purchase_item_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.purchase_items
            FOR EACH ROW EXECUTE FUNCTION public.phase4_purchase_item_guard()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.purchases'::regclass
                     AND tgname = 'trg_p4_purchase_status_guard'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_purchase_status_guard
            BEFORE INSERT OR UPDATE OF purchase_status ON public.purchases
            FOR EACH ROW EXECUTE FUNCTION public.phase4_purchase_status_guard()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.purchases'::regclass
                     AND tgname = 'trg_p4_receive_purchase_inventory'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_receive_purchase_inventory
            AFTER UPDATE OF purchase_status ON public.purchases
            FOR EACH ROW EXECUTE FUNCTION public.phase4_receive_purchase_inventory()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.sale_items'::regclass
                     AND tgname = 'trg_p4_sale_item_guard'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_sale_item_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.sale_items
            FOR EACH ROW EXECUTE FUNCTION public.phase4_sale_item_guard()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.sales'::regclass
                     AND tgname = 'trg_p4_sale_status_guard'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_sale_status_guard
            BEFORE INSERT OR UPDATE OF sale_status ON public.sales
            FOR EACH ROW EXECUTE FUNCTION public.phase4_sale_status_guard()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.sales'::regclass
                     AND tgname = 'trg_p4_apply_sale_inventory'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_apply_sale_inventory
            AFTER UPDATE OF sale_status ON public.sales
            FOR EACH ROW EXECUTE FUNCTION public.phase4_apply_sale_inventory()';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.purchases'::regclass
                     AND tgname = 'trg_p4_audit_purchases'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_purchases
            AFTER INSERT OR UPDATE OR DELETE ON public.purchases
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.purchase_items'::regclass
                     AND tgname = 'trg_p4_audit_purchase_items'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_purchase_items
            AFTER INSERT OR UPDATE OR DELETE ON public.purchase_items
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.sales'::regclass
                     AND tgname = 'trg_p4_audit_sales'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_sales
            AFTER INSERT OR UPDATE OR DELETE ON public.sales
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.sale_items'::regclass
                     AND tgname = 'trg_p4_audit_sale_items'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_sale_items
            AFTER INSERT OR UPDATE OR DELETE ON public.sale_items
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.vehicle_inventory'::regclass
                     AND tgname = 'trg_p4_audit_vehicle_inventory'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_vehicle_inventory
            AFTER INSERT OR UPDATE OR DELETE ON public.vehicle_inventory
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.payments'::regclass
                     AND tgname = 'trg_p4_audit_payments'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p4_audit_payments
            AFTER INSERT OR UPDATE OR DELETE ON public.payments
            FOR EACH ROW EXECUTE FUNCTION public.phase4_audit_commerce_change()';
    END IF;
END
$$;

COMMIT;

-- Rollback note: these workflow/audit triggers preserve history and may append
-- audit rows after use. Do not drop them automatically or replay transactions
-- in reverse. Disable new routes and retain records unless an approved,
-- isolated-test-only down migration is prepared.
