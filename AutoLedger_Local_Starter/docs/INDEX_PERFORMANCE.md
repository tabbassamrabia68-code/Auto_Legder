# Index Performance Demonstration

The query filters by vehicle and sorts its service dates. This exact query was
run before and after `db/001_indexes.sql`:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT service_id, vehicle_id, service_date
FROM service_records
WHERE vehicle_id = 1
ORDER BY service_date DESC;
```

Baseline (before `db/001_indexes.sql`, 76 service rows, before the service cost
column was added):

```text
Sort (actual time=0.172..0.173 rows=2 loops=1)
	Sort Key: service_date DESC
	Sort Method: quicksort
	-> Seq Scan on service_records (actual time=0.100..0.150 rows=2 loops=1)
			 Filter: (vehicle_id = 1)
			 Rows Removed by Filter: 74
Execution Time: 0.189 ms
```

After applying the indexes and running `ANALYZE service_records`, PostgreSQL
still chose a sequential scan. With only 76 rows, that is cheaper than an index
lookup; this is expected and not a failed migration. The composite index
supports ordered latest-service lookups as the table grows and is also
available to the lateral lookup in `vw_vehicle_summary`.

After:

```text
Sort (actual time=0.228..0.230 rows=2 loops=1)
	Sort Key: service_date DESC
	Sort Method: quicksort
	-> Seq Scan on service_records (actual time=0.059..0.124 rows=2 loops=1)
			 Filter: (vehicle_id = 1)
			 Rows Removed by Filter: 74
Planning Time: 2.031 ms
Execution Time: 0.305 ms
```