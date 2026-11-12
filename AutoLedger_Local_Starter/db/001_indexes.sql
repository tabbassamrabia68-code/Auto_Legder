BEGIN;

ALTER TABLE service_records
    ADD COLUMN IF NOT EXISTS cost NUMERIC(12, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_service_cost_nonnegative'
          AND conrelid = 'public.service_records'::regclass
    ) THEN
        ALTER TABLE service_records
            ADD CONSTRAINT chk_service_cost_nonnegative CHECK (cost IS NULL OR cost >= 0);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_inspections_inspector ON inspections (inspector_id);
CREATE INDEX IF NOT EXISTS idx_inspection_vehicle ON inspections (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_verification_verified_by ON verification_records (verified_by);
CREATE INDEX IF NOT EXISTS idx_verification_vehicle ON verification_records (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role_id);
CREATE INDEX IF NOT EXISTS idx_document_vehicle ON documents (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owner ON ownership_records (owner_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_documents_expiry_date ON documents (expiry_date)
    WHERE expiry_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_service_vehicle ON service_records (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_service_vehicle_date_cost
    ON service_records (vehicle_id, service_date DESC) INCLUDE (cost);
CREATE INDEX IF NOT EXISTS idx_repair_vehicle ON repair_records (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_repair_vehicle_date_cost
    ON repair_records (vehicle_id, repair_date DESC) INCLUDE (cost);
CREATE INDEX IF NOT EXISTS idx_mileage_vehicle ON mileage_records (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_mileage_vehicle_latest
    ON mileage_records (vehicle_id, recorded_date DESC, mileage_id DESC) INCLUDE (mileage);
CREATE INDEX IF NOT EXISTS idx_ownership_vehicle_active
    ON ownership_records (vehicle_id, start_date DESC)
    WHERE ownership_status = 'ACTIVE';

COMMIT;