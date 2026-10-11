BEGIN;

CREATE OR REPLACE VIEW vw_vehicle_summary AS
SELECT
    v.vehicle_id,
    v.vin,
    v.registration_no,
    v.brand,
    v.model,
    v.model_year,
    v.color,
    v.fuel_type,
    v.transmission,
    current_owner.full_name AS current_owner,
    current_owner.owner_id AS current_owner_id,
    latest_mileage.mileage AS latest_mileage,
    latest_mileage.recorded_date AS latest_mileage_date,
    last_service.service_date AS last_service_date,
    last_service.service_type AS last_service_type,
    last_service.cost AS last_service_cost,
    COALESCE(document_summary.document_count, 0) AS document_count,
    document_summary.document_statuses,
    document_summary.next_expiry_date
FROM vehicles v
LEFT JOIN LATERAL (
    SELECT o.owner_id, o.full_name
    FROM ownership_records ow
    JOIN owners o ON o.owner_id = ow.owner_id
    WHERE ow.vehicle_id = v.vehicle_id AND ow.ownership_status = 'ACTIVE'
    ORDER BY ow.start_date DESC, ow.ownership_id DESC
    LIMIT 1
) current_owner ON TRUE
LEFT JOIN LATERAL (
    SELECT mr.mileage, mr.recorded_date
    FROM mileage_records mr
    WHERE mr.vehicle_id = v.vehicle_id
    ORDER BY mr.recorded_date DESC, mr.mileage_id DESC
    LIMIT 1
) latest_mileage ON TRUE
LEFT JOIN LATERAL (
    SELECT sr.service_date, sr.service_type, sr.cost
    FROM service_records sr
    WHERE sr.vehicle_id = v.vehicle_id
    ORDER BY sr.service_date DESC, sr.service_id DESC
    LIMIT 1
) last_service ON TRUE
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) AS document_count,
        STRING_AGG(DISTINCT
            CASE
                WHEN d.status = 'CANCELLED' THEN 'CANCELLED'
                WHEN d.expiry_date < CURRENT_DATE THEN 'EXPIRED'
                ELSE d.status
            END,
            ', ' ORDER BY
            CASE
                WHEN d.status = 'CANCELLED' THEN 'CANCELLED'
                WHEN d.expiry_date < CURRENT_DATE THEN 'EXPIRED'
                ELSE d.status
            END
        ) AS document_statuses,
        MIN(d.expiry_date) FILTER (WHERE d.expiry_date >= CURRENT_DATE) AS next_expiry_date
    FROM documents d
    WHERE d.vehicle_id = v.vehicle_id
) document_summary ON TRUE;

CREATE OR REPLACE VIEW vw_expiring_documents AS
SELECT
    d.document_id,
    d.vehicle_id,
    v.registration_no,
    v.vin,
    d.document_type,
    d.document_number,
    d.issue_date,
    d.expiry_date,
    d.status,
    d.expiry_date - CURRENT_DATE AS days_until_expiry
FROM documents d
JOIN vehicles v ON v.vehicle_id = d.vehicle_id
WHERE d.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30
  AND d.status <> 'CANCELLED';

CREATE OR REPLACE VIEW vw_monthly_costs AS
WITH service_costs AS (
    SELECT DATE_TRUNC('month', service_date)::DATE AS month,
           SUM(COALESCE(cost, 0)) AS service_cost,
           COUNT(*) AS service_count
    FROM service_records
    GROUP BY DATE_TRUNC('month', service_date)::DATE
), repair_costs AS (
    SELECT DATE_TRUNC('month', repair_date)::DATE AS month,
           SUM(COALESCE(cost, 0)) AS repair_cost,
           COUNT(*) AS repair_count
    FROM repair_records
    GROUP BY DATE_TRUNC('month', repair_date)::DATE
)
SELECT
    COALESCE(s.month, r.month) AS month,
    COALESCE(s.service_cost, 0)::NUMERIC(14, 2) AS service_cost,
    COALESCE(r.repair_cost, 0)::NUMERIC(14, 2) AS repair_cost,
    (COALESCE(s.service_cost, 0) + COALESCE(r.repair_cost, 0))::NUMERIC(14, 2) AS total_cost,
    COALESCE(s.service_count, 0) AS service_count,
    COALESCE(r.repair_count, 0) AS repair_count
FROM service_costs s
FULL OUTER JOIN repair_costs r ON r.month = s.month;

CREATE OR REPLACE VIEW vw_owner_history AS
SELECT
    o.owner_id,
    o.full_name,
    o.email,
    o.phone,
    v.vehicle_id,
    v.vin,
    v.registration_no,
    v.brand,
    v.model,
    ow.ownership_id,
    ow.start_date,
    ow.end_date,
    ow.ownership_status
FROM owners o
JOIN ownership_records ow ON ow.owner_id = o.owner_id
JOIN vehicles v ON v.vehicle_id = ow.vehicle_id;

COMMIT;