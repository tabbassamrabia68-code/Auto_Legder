# AutoLedger Viva Questions

1. **What does AutoLedger store?** Vehicle identity, owners and ownership periods, service/repair, mileage, inspections, documents, verification, users/roles, and audit history.
2. **Why separate `vehicles` and `owners`?** Each represents a different entity; ownership links them over time without duplicating either entity's details.
3. **Why is ownership a separate table?** A vehicle can have many owners over its lifetime, and each ownership period has its own dates and status.
4. **What is the primary key of `vehicles`?** `vehicle_id`, a generated surrogate key used for stable foreign-key references.
5. **Which vehicle attributes are unique?** VIN, registration number, and engine number each have a unique constraint.
6. **Why keep both a surrogate key and VIN?** The integer key is compact and stable for joins; VIN remains a real-world alternate key protected by uniqueness.
7. **What prevents invalid model years?** `chk_vehicle_year` restricts model years to 1980 through 2035.
8. **How are users assigned permissions?** `users.role_id` references the unique role name in `roles`.
9. **How are passwords stored?** bcrypt hashes are stored in `users.password_hash`; plaintext passwords are never stored.
10. **Why can `password_hash` be null?** Existing accounts remain intact after migration and can be initialized individually instead of inventing passwords for users.
11. **How does login work?** The API verifies the bcrypt hash and returns a signed, expiring JWT; protected requests resolve the active user and role from the database.
12. **What can an Owner/Viewer do?** Read ledger and dashboard data; write operations and audit access are role-restricted.
13. **How is one active owner enforced?** A partial unique index allows at most one `ownership_records` row per vehicle where status is `ACTIVE`.
14. **How does ownership transfer stay atomic?** `transfer_ownership` locks the vehicle, closes the old active row, inserts the new active row, and runs in one transaction.
15. **Why lock the vehicle row during transfer?** Competing transfers for the same vehicle serialize before changing active ownership.
16. **How is odometer rollback detected?** A `BEFORE INSERT OR UPDATE` trigger compares a proposed reading with that vehicle's latest reading and raises check-violation SQLSTATE `23514` if it decreases.
17. **What happens to expired documents?** A trigger marks a document expired on insert/update; a refresh function updates documents whose expiry date has passed, and views calculate effective status for reads.
18. **What is written to `audit_logs`?** Vehicle and ownership insert/update/delete triggers record the action, entity key, row snapshot, timestamp, and current app user when supplied.
19. **Why is the audit user nullable?** Database changes from legacy scripts or unauthenticated local maintenance may have no application user context.
20. **Why index foreign-key columns?** PostgreSQL does not automatically index the referencing side of a foreign key; indexes speed joins and referenced-row checks.
21. **Why add an index on `documents.expiry_date`?** Expiry dashboards and alerts filter by a date range, so the index supports that access path.
22. **What does `vw_vehicle_summary` provide?** One read model combining vehicle details with active owner, latest mileage, last service, and document status information.
23. **How are monthly maintenance costs calculated?** Service and repair amounts are grouped by calendar month and combined in `vw_monthly_costs`.
24. **Why might `EXPLAIN ANALYZE` still show a sequential scan?** For a tiny table, reading all pages can cost less than using an index; the planner's choice is size- and statistics-dependent.
25. **How do you keep the database changes safe to reapply?** Migrations use `IF NOT EXISTS`, replaceable functions/views, and guarded seed inserts; the helper does not drop tables or existing rows.