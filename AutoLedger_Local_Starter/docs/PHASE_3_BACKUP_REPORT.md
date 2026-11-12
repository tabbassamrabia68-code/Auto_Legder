# AutoLedger Phase 3 Backup Report

**Backup created:** 2026-11-07 19:13:04.657 +05:00

**Status:** Created and verified with PostgreSQL 18 `pg_restore --list`.

## Backup details

- **File:** `autoledger_db_20261107_191304_305.dump`
- **Full path:** `C:\Users\rabia tabbassam\Desktop\AutoLedgerBackups\autoledger_db_20261107_191304_305.dump`
- **Format:** PostgreSQL custom archive (`pg_dump --format=custom`)
- **Size:** 77,334 bytes (about 75.5 KiB)
- **SHA-256:** `10597AAD0EF43DCB26828EC6F085A325F47DC990C129A9819B9F4FC63C4DBE47`

## Archive verification

PostgreSQL 18.6 `pg_restore --list` exited successfully. The archive TOC
contains:

- 16 public table definitions, matching the 16 live base tables.
- 16 public table-data entries, one for each expected table.
- All 4 expected public views: `vw_expiring_documents`,
  `vw_monthly_costs`, `vw_owner_history`, and `vw_vehicle_summary`.
- Function, constraint, index, and sequence archive entries.

The archive listing was checked for the full expected table, table-data, and
view names, with none missing. Listing an archive verifies that PostgreSQL can
read its table of contents; **the archive has not been restored into a
separate test database**, so a restore drill remains a recommended additional
check before any production migration.

## Connection and tools

- Database: `autoledger_db`
- Host: `localhost` (read from workspace `.env`)
- Port: `2005` (read from workspace `.env`, passed as an integer)
- PostgreSQL server: `18.6`
- Client tools: PostgreSQL `pg_dump` and `pg_restore` `18.6`
- Credentials: read from `.env`; the password was supplied through the
  process-scoped `PGPASSWORD` environment variable and is not recorded here.

## Live database snapshot

A read-only catalog/count check completed after backup creation and reported
16 base tables, 95 columns, 16 primary keys, 14 foreign keys, 5 unique
constraints, 14 check constraints, 46 indexes, 4 views, and 13 named row
triggers. Current counts were 41 vehicles, 39 owners, 97 services, 41
ownership records, 40 inspections, 38 repairs, 116 mileage records, 78
documents, 40 verifications, 7 users, and 316 audit logs. Purchases and sales
had zero rows at that check. No database changes were made by the backup or
catalog inspection.

## Existing backup files and warnings

- The previously verified file
  `C:\Users\rabia tabbassam\Desktop\AutoLedgerBackups\autoledger_db_20261012_221111.dump`
  was present (61,953 bytes) and was not overwritten or deleted. It was not
  revalidated as part of this run.
- A prior failed backup attempt had left a zero-byte file named
  `autoledger_db_20261107_191000.dump`. It was left untouched. The successful
  retry used a different, non-existing timestamped filename.
- An initial archive-count check compared standalone index TOC entries to the
  live total index count. PostgreSQL represents indexes backing constraints
  via constraint entries, so that comparison was not a valid test. The archive
  was rechecked correctly: `pg_restore --list` succeeded, and every expected
  table definition, table-data entry, and view was present.
- No migration or seed script was executed, and the backup was not restored
  to the live database.
