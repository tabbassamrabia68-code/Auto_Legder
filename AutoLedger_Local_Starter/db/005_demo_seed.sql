BEGIN;

UPDATE service_records
   SET cost = 2500 + (service_id % 9) * 650
 WHERE cost IS NULL;

INSERT INTO documents (vehicle_id, document_type, document_number, issue_date, expiry_date, status)
SELECT v.vehicle_id, 'Demo registration', 'AL-DEMO-EXPIRING-' || v.vehicle_id,
       CURRENT_DATE - 350, CURRENT_DATE + 14, 'VALID'
FROM vehicles v
WHERE v.vehicle_id = (SELECT MIN(vehicle_id) FROM vehicles)
  AND NOT EXISTS (
      SELECT 1 FROM documents d
      WHERE d.document_number = 'AL-DEMO-EXPIRING-' || v.vehicle_id
  );

INSERT INTO documents (vehicle_id, document_type, document_number, issue_date, expiry_date, status)
SELECT v.vehicle_id, 'Demo insurance', 'AL-DEMO-EXPIRED-' || v.vehicle_id,
       CURRENT_DATE - 370, CURRENT_DATE - 5, 'VALID'
FROM vehicles v
WHERE v.vehicle_id = (SELECT MIN(vehicle_id) FROM vehicles)
  AND NOT EXISTS (
      SELECT 1 FROM documents d
      WHERE d.document_number = 'AL-DEMO-EXPIRED-' || v.vehicle_id
  );

COMMIT;