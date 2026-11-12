# AutoLedger Phase 9 — Deployment Readiness

## Status

Deployment preparation is complete; **nothing has been deployed**. The
container configuration is an optional application-only template. It does
not start PostgreSQL, run migrations, seed data, or access the live database
unless an operator explicitly supplies those settings.

## Container files

- `Dockerfile` builds the existing FastAPI/static frontend application as a
  non-root user.
- `docker-compose.yml` runs only the app and requires explicit production
  environment values. PostgreSQL remains external.
- `.dockerignore` excludes `.env`, virtual environments, dumps, tests, and
  other local-only files from the build context.

No Docker engine or Node.js runtime was installed in the development
environment; the Docker image was not built, and no deployment was attempted.

## Production prerequisites

Before deploying, an operator must:

1. Review the current schema and proposed Phase 4/7 migration drafts.
2. Obtain separate approval for each production database migration.
3. Take and verify a fresh PostgreSQL 18 backup outside the repository.
4. Restore the backup to a separate database and rehearse migrations,
   backfill decisions, API tests, and rollback.
5. Decide how to provision the first Super Admin and record that action in
   the audit trail.
6. Supply secrets using the host's secret manager, not a tracked Compose
   file, Docker build argument, source code, or terminal log.
7. Set `APP_ENV=production`, `DATABASE_URL`, `AUTH_SECRET_KEY`,
   `CORS_ALLOWED_ORIGINS`, and `TRUSTED_HOSTS`. The application enforces
   PostgreSQL TLS and secure refresh cookies in production.
8. Terminate HTTPS at an approved reverse proxy/load balancer, restrict
   database network access to the application, and use a least-privilege
   PostgreSQL service account.
9. Validate health checks, session expiry/revocation, permissions, backup
   monitoring, log redaction, and restore procedures in the target
   environment.

Do not pass the existing local database password through a command-line
argument. Configure deployment secrets through the platform's protected
environment/secret mechanism. Do not copy the development `.env` into an
image.

## Build and run (after approval)

From `AutoLedger_Local_Starter`, with Docker installed and environment
variables provisioned securely:

```powershell
docker compose config -q
docker compose build
docker compose up -d
```

The configuration publishes the app on `${APP_PORT:-8001}` and connects only
to the externally configured `DATABASE_URL`. Do not run these commands until
the production target and migration status have been approved.

## Rollback

- Keep the previous application image/release available and route traffic
  back to it if health or smoke checks fail.
- Preserve the pre-migration backup and restore it only under an approved
  incident procedure.
- The app-only container rollback does not reverse database changes.
- Do not automatically reverse additive schema changes or delete migrated
  data. Use a reviewed compensating migration only after checking whether
  newer application versions have written to the new structures.

## Current blockers

- Phase 4 commerce and Phase 7 authentication/RBAC extensions are not
  installed in the live database.
- The original `autoledger_db` has no Phase 4/7 schema. The local
  `autoledger_dev_clone` does; the application now resolves selected business
  memberships and filters commerce API requests, with cross-business tests on
  that clone. Business/member administration, tenant-aware database triggers,
  shared vehicle/history authorization, browser switching, and broader
  tenant tests remain incomplete. Shared multi-tenant deployment is blocked.
- The final seven-role policy is implemented in the current worktree, but the
  isolated backend suite and Viewer frontend smoke checks now pass. Legacy
  users are preserved and must be reviewed individually before reassignment;
  no production role migration or account mapping has been approved.
- Production migration approval and Super Admin provisioning remain
  outstanding.
- The container template has not been built in this environment.
- Production TLS, reverse proxy, secrets, monitoring, and recovery have not
  been configured or verified.
