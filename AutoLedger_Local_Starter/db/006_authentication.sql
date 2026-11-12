BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

INSERT INTO roles (role_name, description)
VALUES ('Owner/Viewer', 'Read-only access to vehicle ledger data')
ON CONFLICT (role_name) DO NOTHING;

COMMIT;