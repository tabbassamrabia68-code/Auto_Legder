-- 1. Vehicle summary with current owner and latest ledger facts.
SELECT * FROM vw_vehicle_summary ORDER BY registration_no LIMIT 25;

-- 2. Search VIN/registration and show the matching current owner.
SELECT vehicle_id, vin, registration_no, brand, model, current_owner
FROM vw_vehicle_summary
WHERE vin ILIKE '%TEST%' OR registration_no ILIKE '%KHI%'
ORDER BY registration_no;

-- 3. Owners with multiple vehicles (JOIN, GROUP BY, HAVING).
SELECT o.owner_id, o.full_name, COUNT(DISTINCT ow.vehicle_id) AS vehicle_count
FROM owners o
JOIN ownership_records ow ON ow.owner_id = o.owner_id
WHERE ow.ownership_status = 'ACTIVE'
GROUP BY o.owner_id, o.full_name
HAVING COUNT(DISTINCT ow.vehicle_id) > 1
ORDER BY vehicle_count DESC;

-- 4. Documents due in the coming month.
SELECT * FROM vw_expiring_documents ORDER BY expiry_date, registration_no;

-- 5. Monthly maintenance spend from the service and repair ledgers.
SELECT * FROM vw_monthly_costs ORDER BY month DESC;

-- 6. Rank vehicles by lifetime maintenance spend (CTE + window function).
WITH vehicle_spend AS (
    SELECT v.vehicle_id, v.registration_no, v.brand, v.model,
           COALESCE(s.service_cost, 0) + COALESCE(r.repair_cost, 0) AS total_cost
    FROM vehicles v
    LEFT JOIN (SELECT vehicle_id, SUM(COALESCE(cost, 0)) AS service_cost
               FROM service_records GROUP BY vehicle_id) s USING (vehicle_id)
    LEFT JOIN (SELECT vehicle_id, SUM(COALESCE(cost, 0)) AS repair_cost
               FROM repair_records GROUP BY vehicle_id) r USING (vehicle_id)
)
SELECT *, DENSE_RANK() OVER (ORDER BY total_cost DESC) AS spend_rank
FROM vehicle_spend
ORDER BY spend_rank, registration_no;

-- 7. Show ownership timeline and flag overlapping active ownership candidates.
SELECT *,
       LAG(end_date) OVER (PARTITION BY vehicle_id ORDER BY start_date) AS prior_end_date
FROM ownership_records
ORDER BY vehicle_id, start_date;

-- 8. Detect historical odometer drops in imported/legacy records.
WITH mileage_order AS (
    SELECT vehicle_id, recorded_date, mileage, source,
           LAG(mileage) OVER (PARTITION BY vehicle_id ORDER BY recorded_date, mileage_id) AS prior_mileage
    FROM mileage_records
)
SELECT * FROM mileage_order
WHERE prior_mileage IS NOT NULL AND mileage < prior_mileage
ORDER BY vehicle_id, recorded_date;

-- 9. Vehicles whose latest service is older than one year (correlated subquery).
SELECT v.vehicle_id, v.registration_no, v.brand, v.model
FROM vehicles v
WHERE (SELECT MAX(s.service_date) FROM service_records s WHERE s.vehicle_id = v.vehicle_id)
      < CURRENT_DATE - INTERVAL '1 year'
ORDER BY v.registration_no;

-- 10. Monthly service versus repair cost by brand (JOIN + GROUP BY).
SELECT v.brand,
       DATE_TRUNC('month', costs.event_date)::DATE AS month,
       SUM(CASE WHEN costs.kind = 'SERVICE' THEN costs.cost ELSE 0 END) AS service_cost,
       SUM(CASE WHEN costs.kind = 'REPAIR' THEN costs.cost ELSE 0 END) AS repair_cost
FROM vehicles v
JOIN (
    SELECT vehicle_id, service_date AS event_date, COALESCE(cost, 0) AS cost, 'SERVICE' AS kind
    FROM service_records
    UNION ALL
    SELECT vehicle_id, repair_date, COALESCE(cost, 0), 'REPAIR'
    FROM repair_records
) costs USING (vehicle_id)
GROUP BY v.brand, DATE_TRUNC('month', costs.event_date)
ORDER BY month DESC, v.brand;

-- 11. Latest verification event for each vehicle (LEFT JOIN LATERAL).
SELECT v.vehicle_id, v.registration_no, latest.verification_date,
       latest.result, u.full_name AS verified_by
FROM vehicles v
LEFT JOIN LATERAL (
    SELECT verification_date, result, verified_by
    FROM verification_records vr
    WHERE vr.vehicle_id = v.vehicle_id
    ORDER BY verification_date DESC, verification_id DESC
    LIMIT 1
) latest ON TRUE
LEFT JOIN users u ON u.user_id = latest.verified_by
ORDER BY v.registration_no
LIMIT 25;

-- 12. Document status by vehicle, including dates that have since expired.
SELECT v.vehicle_id, v.registration_no, d.document_type, d.issue_date,
       d.expiry_date,
       CASE
           WHEN d.status <> 'CANCELLED' AND d.expiry_date < CURRENT_DATE THEN 'EXPIRED'
           ELSE d.status
       END AS effective_status
FROM documents d
JOIN vehicles v USING (vehicle_id)
ORDER BY d.expiry_date NULLS LAST, v.registration_no
LIMIT 25;

-- Fraud-detection demo: try a mileage reading below a vehicle's latest reading.
-- The trigger should reject this statement with SQLSTATE 23514; run manually
-- with a valid vehicle_id, and do not disable the trigger to retain test data.
-- INSERT INTO mileage_records (vehicle_id, recorded_date, mileage, source)
-- SELECT vehicle_id, CURRENT_DATE, GREATEST(MAX(mileage) - 1, 0), 'OTHER'
-- FROM mileage_records WHERE vehicle_id = 1 GROUP BY vehicle_id;