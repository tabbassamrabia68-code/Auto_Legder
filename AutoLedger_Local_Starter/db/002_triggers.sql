BEGIN;

CREATE OR REPLACE FUNCTION prevent_mileage_rollback()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    latest_mileage INTEGER;
BEGIN
    SELECT mileage
      INTO latest_mileage
      FROM mileage_records
     WHERE vehicle_id = NEW.vehicle_id
       AND (TG_OP <> 'UPDATE' OR mileage_id <> OLD.mileage_id)
     ORDER BY recorded_date DESC, mileage_id DESC
     LIMIT 1;

    IF latest_mileage IS NOT NULL AND NEW.mileage < latest_mileage THEN
        RAISE EXCEPTION 'Mileage rollback rejected for vehicle %: % is below latest reading %',
            NEW.vehicle_id, NEW.mileage, latest_mileage
            USING ERRCODE = '23514', CONSTRAINT = 'trg_mileage_no_rollback';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mileage_no_rollback ON mileage_records;
CREATE TRIGGER trg_mileage_no_rollback
BEFORE INSERT OR UPDATE OF vehicle_id, recorded_date, mileage ON mileage_records
FOR EACH ROW EXECUTE FUNCTION prevent_mileage_rollback();

CREATE OR REPLACE FUNCTION audit_ledger_row_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_data JSONB;
    record_id INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        row_data := to_jsonb(OLD);
    ELSE
        row_data := to_jsonb(NEW);
    END IF;

    IF TG_TABLE_NAME = 'vehicles' THEN
        record_id := (row_data ->> 'vehicle_id')::INTEGER;
    ELSE
        record_id := (row_data ->> 'ownership_id')::INTEGER;
    END IF;

    INSERT INTO audit_logs (user_id, action, entity_name, entity_id, details)
    VALUES (
        NULL,
        TG_OP,
        TG_TABLE_NAME,
        record_id,
        jsonb_build_object('row', row_data)::TEXT
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_vehicles ON vehicles;
CREATE TRIGGER trg_audit_vehicles
AFTER INSERT OR UPDATE OR DELETE ON vehicles
FOR EACH ROW EXECUTE FUNCTION audit_ledger_row_change();

DROP TRIGGER IF EXISTS trg_audit_ownership_records ON ownership_records;
CREATE TRIGGER trg_audit_ownership_records
AFTER INSERT OR UPDATE OR DELETE ON ownership_records
FOR EACH ROW EXECUTE FUNCTION audit_ledger_row_change();

CREATE OR REPLACE FUNCTION set_document_expiry_status()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status <> 'CANCELLED' AND NEW.expiry_date IS NOT NULL
       AND NEW.expiry_date < CURRENT_DATE THEN
        NEW.status := 'EXPIRED';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_document_expiry_status ON documents;
CREATE TRIGGER trg_document_expiry_status
BEFORE INSERT OR UPDATE OF expiry_date, status ON documents
FOR EACH ROW EXECUTE FUNCTION set_document_expiry_status();

CREATE OR REPLACE FUNCTION refresh_expired_document_statuses()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    changed_rows INTEGER;
BEGIN
    UPDATE documents
       SET status = 'EXPIRED'
     WHERE status NOT IN ('EXPIRED', 'CANCELLED')
       AND expiry_date < CURRENT_DATE;
    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    RETURN changed_rows;
END;
$$;

SELECT refresh_expired_document_statuses();

COMMIT;