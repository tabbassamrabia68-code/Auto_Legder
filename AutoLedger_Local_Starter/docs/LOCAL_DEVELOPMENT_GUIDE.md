# AutoLedger Local Development Guide

## Requirements

- Windows PowerShell
- Python 3.10 or newer
- PostgreSQL 18 for the documented current environment
- Existing workspace PostgreSQL settings in the root `.env`
- Existing application port `8001`

The project is FastAPI-served HTML/CSS/JavaScript; a separate frontend
development server is not required.

## Preserve the existing environment

Run commands from the workspace root. Do not copy over an existing `.env`;
create it only if it does not exist:

```powershell
Set-Location 'C:\Users\<you>\Desktop\Auto_legder'
if (-not (Test-Path .\.env)) {
  Copy-Item .\AutoLedger_Local_Starter\.env.example .\.env
}
```

The root `.env` must contain the configured `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, and `AUTH_SECRET_KEY`. Preserve the configured
PostgreSQL port; this workspace currently verifies as `2005`. Never paste or
print credentials. The current local `.env` points to `autoledger_dev_clone`;
the original `autoledger_db` was not changed. The application rejects a
missing/short auth key.

If creating a local virtual environment for the first time:

```powershell
py -m venv .\AutoLedger_Local_Starter\.venv
& .\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pip install -r .\AutoLedger_Local_Starter\requirements.txt
```

## Start the application

```powershell
Set-Location 'C:\Users\<you>\Desktop\Auto_legder'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Port 8001
```

Open `http://127.0.0.1:8001`. The health route is
`http://127.0.0.1:8001/api/health`, API docs are at `/docs`, and OpenAPI is at
`/openapi.json`.

The start script does not reset or migrate the database. Do not run
`db/reset_and_reseed.ps1` against the existing database.

## Tests

Database tests write records. Prefer a fresh disposable database whose name
begins `autoledger_test_`. The explicitly authorized `autoledger_dev_clone`
can be used with the opt-in below; it accumulates test data and is not clean.

```powershell
Set-Location 'C:\Users\<you>\Desktop\Auto_legder'
$env:AUTOLEDGER_TEST_DB_NAME = 'autoledger_dev_clone'
$env:AUTOLEDGER_ALLOW_DEV_CLONE = '1'
& .\AutoLedger_Local_Starter\.venv\Scripts\python.exe -m pytest .\AutoLedger_Local_Starter\tests -q
Remove-Item Env:\AUTOLEDGER_TEST_DB_NAME,Env:\AUTOLEDGER_ALLOW_DEV_CLONE
```

The fixture explicitly rejects `autoledger_db`, requires localhost:2005 for
the opted-in clone, and ignores `DATABASE_URL` during tests. Verify the target
database name and port before running any integration suite.

## Database and migration safety

The original `autoledger_db` retains the legacy 16-table vehicle-history
schema. The configured local clone has the Phase 4/7 schema. SQL design drafts
are under
`AutoLedger_Local_Starter\db\proposed_phase4\` and
`AutoLedger_Local_Starter\db\proposed_phase7\`; they have been applied only to
the development clone. Do not run these files against `autoledger_db`. A separate review,
fresh backup, isolated restore, and explicit approval are required before any
live migration.

Use the existing backup/restore procedure documented in
[PHASE_3_BACKUP_REPORT.md](./PHASE_3_BACKUP_REPORT.md). Keep backup files
outside the Git repository. The `.env` file and passwords must never be
committed.

## Current local limitations

- The original `autoledger_db` still shows a migration gate for commerce.
- Existing membership selection and commerce filtering are implemented on
  the clone; business/member administration and tenant-aware database
  triggers are still incomplete. Do not use as a shared multi-business
  production service.
- The legacy role catalog does not match the seven-role application policy;
  no automatic role conversion occurs.
- Vehicle document/image upload, MFA, password recovery, and deployment are
  not available.

For current verified functionality and blockers, see
[FINAL_PROJECT_AUDIT.md](./FINAL_PROJECT_AUDIT.md) and
[PHASE_9_DEPLOYMENT_READINESS.md](./PHASE_9_DEPLOYMENT_READINESS.md).
