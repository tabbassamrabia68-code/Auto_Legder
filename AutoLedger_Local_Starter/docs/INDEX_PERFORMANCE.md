# Index Performance Demonstration

The query filters by vehicle and sorts its service dates. The historical
baseline below was recorded before `db/001_indexes.sql`; the current plan was
captured from the configured local database after the indexes were installed.

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

After applying the indexes, PostgreSQL still chose a sequential scan. The live
table has 76 rows, so scanning it is cheaper than an index lookup. The composite
index supports ordered latest-service lookups as the table grows and remains
available to the lateral lookup in `vw_vehicle_summary`.

After:

```text
Sort (actual time=0.041..0.042 rows=2 loops=1)
	Sort Key: service_date DESC
	Sort Method: quicksort  Memory: 25kB
	Buffers: shared hit=6
	-> Seq Scan on service_records (actual time=0.009..0.026 rows=2 loops=1)
				Filter: (vehicle_id = 1)
				Rows Removed by Filter: 74
				Buffers: shared hit=3
Planning Time: 0.181 ms
Execution Time: 0.051 ms
```

The current after-plan was collected with `EXPLAIN (ANALYZE, BUFFERS)` against
the local 76-row service table. Timings vary between runs and are included as
observed output, not as a guaranteed performance improvement.