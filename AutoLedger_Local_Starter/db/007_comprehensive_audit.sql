BEGIN;

CREATE OR REPLACE FUNCTION audit_ledger_row_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_data JSONB;
    record_id INTEGER;
    actor_id INTEGER;
BEGIN
    actor_id := NULLIF(current_setting('app.user_id', TRUE), '')::INTEGER;

    IF TG_OP = 'DELETE' THEN
        row_data := to_jsonb(OLD) - 'password_hash';
        record_id := (to_jsonb(OLD) ->> CASE TG_TABLE_NAME
            WHEN 'roles' THEN 'role_id'
            WHEN 'users' THEN 'user_id'
            WHEN 'owners' THEN 'owner_id'
            WHEN 'vehicles' THEN 'vehicle_id'
            WHEN 'ownership_records' THEN 'ownership_id'
            WHEN 'service_records' THEN 'service_id'
            WHEN 'repair_records' THEN 'repair_id'
            WHEN 'mileage_records' THEN 'mileage_id'
            WHEN 'inspections' THEN 'inspection_id'
            WHEN 'documents' THEN 'document_id'
            WHEN 'verification_records' THEN 'verification_id'
        END)::INTEGER;
    ELSE
        row_data := to_jsonb(NEW) - 'password_hash';
        record_id := (to_jsonb(NEW) ->> CASE TG_TABLE_NAME
            WHEN 'roles' THEN 'role_id'
            WHEN 'users' THEN 'user_id'
            WHEN 'owners' THEN 'owner_id'
            WHEN 'vehicles' THEN 'vehicle_id'
            WHEN 'ownership_records' THEN 'ownership_id'
            WHEN 'service_records' THEN 'service_id'
            WHEN 'repair_records' THEN 'repair_id'
            WHEN 'mileage_records' THEN 'mileage_id'
            WHEN 'inspections' THEN 'inspection_id'
            WHEN 'documents' THEN 'document_id'
            WHEN 'verification_records' THEN 'verification_id'
        END)::INTEGER;
    END IF;

    INSERT INTO audit_logs (user_id, action, entity_name, entity_id, details)
    VALUES (
        actor_id,
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

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'roles', 'users', 'owners', 'vehicles', 'ownership_records',
        'service_records', 'repair_records', 'mileage_records', 'inspections',
        'documents', 'verification_records'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_audit_%I ON %I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_audit_%I AFTER INSERT OR UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION audit_ledger_row_change()',
            table_name,
            table_name
        );
    END LOOP;
END;
$$;

COMMIT;