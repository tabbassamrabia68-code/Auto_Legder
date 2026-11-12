-- PROPOSED — NOT EXECUTED
-- Phase 7 additive authentication, RBAC, party lifecycle, and payment extensions.
-- Apply only after a fresh backup and isolated-database validation.
-- Existing users, role assignments, business records, and audit history are untouched.
-- The final assignable role set is Super Admin, Admin, Business Owner, Manager,
-- Accountant, Staff, and Viewer. Legacy roles are retained without grants here.

BEGIN;

-- Existing parties remain active by default; no legacy row is removed.
ALTER TABLE public.customers
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE public.suppliers
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- A stable idempotency key lets API retries return the original payment rather
-- than recording a duplicate. NULL remains valid for legacy/manual records.
ALTER TABLE public.payments
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_p7_idempotency_key
    ON public.payments (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Incrementing the version invalidates all previously issued access tokens.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.users'::regclass
          AND conname = 'ck_users_p7_token_version'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT ck_users_p7_token_version CHECK (token_version >= 0);
    END IF;
END
$$;

-- Refresh tokens are stored as SHA-256 digests only. Expiry/revocation is
-- checked and rotation is serialized by the backend transaction.
CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens (
    token_hash CHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    replaced_by_hash CHAR(64),
    CONSTRAINT fk_auth_refresh_tokens_p7_user
        FOREIGN KEY (user_id) REFERENCES public.users (user_id) ON DELETE CASCADE,
    CONSTRAINT ck_auth_refresh_tokens_p7_expiry CHECK (expires_at > issued_at),
    CONSTRAINT ck_auth_refresh_tokens_p7_replacement CHECK (
        replaced_by_hash IS NULL OR replaced_by_hash <> token_hash
    )
);
CREATE INDEX IF NOT EXISTS ix_auth_refresh_tokens_p7_user_expiry
    ON public.auth_refresh_tokens (user_id, expires_at DESC);

-- Add explicit permission catalogs without reassigning existing accounts.
CREATE TABLE IF NOT EXISTS public.permissions (
    permission_key VARCHAR(80) PRIMARY KEY,
    description VARCHAR(240) NOT NULL
);
CREATE TABLE IF NOT EXISTS public.role_permissions (
    role_id INTEGER NOT NULL,
    permission_key VARCHAR(80) NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER,
    CONSTRAINT pk_role_permissions_p7 PRIMARY KEY (role_id, permission_key),
    CONSTRAINT fk_role_permissions_p7_role
        FOREIGN KEY (role_id) REFERENCES public.roles (role_id) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_p7_permission
        FOREIGN KEY (permission_key) REFERENCES public.permissions (permission_key) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_p7_actor
        FOREIGN KEY (granted_by) REFERENCES public.users (user_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_role_permissions_p7_permission
    ON public.role_permissions (permission_key, role_id);

INSERT INTO public.roles (role_name, description)
VALUES
    ('Super Admin', 'Full system access, role and permission administration.'),
    ('Business Owner', 'Business operations, finance, and business reporting.'),
    ('Manager', 'Daily vehicle and business operations with limited finance access.'),
    ('Accountant', 'Payment processing, balances, invoices, and financial reports.'),
    ('Staff', 'Limited operational access.'),
    ('Viewer', 'Read-only vehicle and history access.')
ON CONFLICT (role_name) DO NOTHING;

INSERT INTO public.permissions (permission_key, description)
VALUES
    ('system.manage', 'Manage system-wide configuration and privileged access.'),
    ('roles.manage', 'Manage roles and role permissions.'),
    ('users.manage', 'Manage non-privileged user accounts.'),
    ('audit.read', 'Read the complete audit trail.'),
    ('vehicles.read', 'Read vehicle registry records.'),
    ('vehicles.manage', 'Create and update vehicle records.'),
    ('vehicles.delete', 'Delete permitted vehicle records.'),
    ('owners.read', 'Read owners and ownership history.'),
    ('owners.manage', 'Manage owners and ownership transfers.'),
    ('history.read', 'Read vehicle service, repair, mileage, and document history.'),
    ('history.manage', 'Create permitted vehicle history records.'),
    ('verification.read', 'Read verification and inspection records.'),
    ('verification.manage', 'Create verification and inspection records.'),
    ('customers.read', 'Read customers and customer history.'),
    ('customers.manage', 'Manage customer records.'),
    ('suppliers.read', 'Read suppliers and purchase history.'),
    ('suppliers.manage', 'Manage supplier records.'),
    ('inventory.read', 'Read vehicle stock and valuation.'),
    ('inventory.manage', 'Manage vehicle stock state.'),
    ('purchases.read', 'Read purchase history.'),
    ('purchases.manage', 'Create and manage purchases.'),
    ('sales.read', 'Read sales history.'),
    ('sales.manage', 'Create and manage sales.'),
    ('payments.read', 'Read payment history.'),
    ('payments.manage', 'Record and manage payments.'),
    ('financial.read', 'Read balances and financial summaries.'),
    ('reports.operational', 'Generate operational reports.'),
    ('reports.financial', 'Generate financial reports.'),
    ('invoices.read', 'Generate and read invoices and payment receipts.'),
    ('settings.manage', 'Manage permitted application settings.'),
    ('profile.manage', 'Manage the current user profile and password.')
ON CONFLICT (permission_key) DO NOTHING;

-- Permissions are additive. Existing roles are retained and receive only the
-- explicit mapping below; existing users are not moved between roles.
WITH grants(role_name, permission_key) AS (
    VALUES
      ('Super Admin', 'system.manage'), ('Super Admin', 'roles.manage'),
      ('Super Admin', 'users.manage'), ('Super Admin', 'audit.read'),
      ('Super Admin', 'vehicles.read'), ('Super Admin', 'vehicles.manage'),
      ('Super Admin', 'vehicles.delete'), ('Super Admin', 'owners.read'),
      ('Super Admin', 'owners.manage'), ('Super Admin', 'history.read'),
      ('Super Admin', 'history.manage'), ('Super Admin', 'verification.read'),
      ('Super Admin', 'verification.manage'), ('Super Admin', 'customers.read'),
      ('Super Admin', 'customers.manage'), ('Super Admin', 'suppliers.read'),
      ('Super Admin', 'suppliers.manage'), ('Super Admin', 'inventory.read'),
      ('Super Admin', 'inventory.manage'), ('Super Admin', 'purchases.read'),
      ('Super Admin', 'purchases.manage'), ('Super Admin', 'sales.read'),
      ('Super Admin', 'sales.manage'), ('Super Admin', 'payments.read'),
      ('Super Admin', 'payments.manage'), ('Super Admin', 'financial.read'),
      ('Super Admin', 'reports.operational'), ('Super Admin', 'reports.financial'),
      ('Super Admin', 'invoices.read'), ('Super Admin', 'settings.manage'),
      ('Super Admin', 'profile.manage'),
      ('Admin', 'vehicles.read'), ('Admin', 'owners.read'),
      ('Admin', 'history.read'), ('Admin', 'verification.read'),
      ('Admin', 'customers.read'), ('Admin', 'customers.manage'), ('Admin', 'suppliers.read'),
      ('Admin', 'suppliers.manage'), ('Admin', 'inventory.read'), ('Admin', 'inventory.manage'),
      ('Admin', 'purchases.read'), ('Admin', 'purchases.manage'), ('Admin', 'sales.read'),
      ('Admin', 'sales.manage'), ('Admin', 'payments.read'), ('Admin', 'payments.manage'),
      ('Admin', 'financial.read'), ('Admin', 'reports.operational'),
      ('Admin', 'reports.financial'), ('Admin', 'invoices.read'),
      ('Business Owner', 'vehicles.read'), ('Business Owner', 'owners.read'),
      ('Business Owner', 'history.read'), ('Business Owner', 'verification.read'),
      ('Business Owner', 'customers.read'), ('Business Owner', 'customers.manage'),
      ('Business Owner', 'suppliers.read'), ('Business Owner', 'suppliers.manage'),
      ('Business Owner', 'inventory.read'), ('Business Owner', 'inventory.manage'),
      ('Business Owner', 'purchases.read'), ('Business Owner', 'purchases.manage'),
      ('Business Owner', 'sales.read'), ('Business Owner', 'sales.manage'),
      ('Business Owner', 'payments.read'), ('Business Owner', 'payments.manage'),
      ('Business Owner', 'financial.read'), ('Business Owner', 'reports.operational'),
      ('Business Owner', 'reports.financial'), ('Business Owner', 'invoices.read'),
      ('Manager', 'vehicles.read'), ('Manager', 'owners.read'),
      ('Manager', 'history.read'), ('Manager', 'verification.read'),
      ('Manager', 'customers.read'), ('Manager', 'customers.manage'),
      ('Manager', 'suppliers.read'), ('Manager', 'suppliers.manage'),
      ('Manager', 'inventory.read'), ('Manager', 'inventory.manage'),
      ('Manager', 'purchases.read'), ('Manager', 'purchases.manage'),
      ('Manager', 'sales.read'), ('Manager', 'sales.manage'),
      ('Manager', 'payments.read'), ('Manager', 'reports.operational'),
      ('Accountant', 'customers.read'), ('Accountant', 'suppliers.read'),
      ('Accountant', 'purchases.read'), ('Accountant', 'sales.read'),
      ('Accountant', 'payments.read'), ('Accountant', 'payments.manage'),
      ('Accountant', 'financial.read'), ('Accountant', 'reports.financial'),
      ('Accountant', 'invoices.read'),
      ('Staff', 'vehicles.read'), ('Staff', 'history.read'),
      ('Staff', 'verification.read'),
      ('Viewer', 'vehicles.read'), ('Viewer', 'owners.read'),
      ('Viewer', 'history.read'), ('Viewer', 'verification.read')
)
INSERT INTO public.role_permissions (role_id, permission_key)
SELECT r.role_id, g.permission_key
FROM grants g
JOIN public.roles r ON r.role_name = g.role_name
JOIN public.permissions p ON p.permission_key = g.permission_key
ON CONFLICT (role_id, permission_key) DO NOTHING;

CREATE OR REPLACE FUNCTION public.phase7_audit_role_permission_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row JSONB;
    v_actor_id INTEGER;
BEGIN
    v_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    v_actor_id := NULLIF(current_setting('app.user_id', true), '')::INTEGER;
    INSERT INTO public.audit_logs (user_id, action, entity_name, entity_id, details)
    VALUES (v_actor_id, TG_OP, 'role_permissions',
            (v_row ->> 'role_id')::INTEGER, v_row::TEXT);
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgrelid = 'public.role_permissions'::regclass
                     AND tgname = 'trg_p7_audit_role_permissions'
                     AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER trg_p7_audit_role_permissions
            AFTER INSERT OR UPDATE OR DELETE ON public.role_permissions
            FOR EACH ROW EXECUTE FUNCTION public.phase7_audit_role_permission_change()';
    END IF;
END
$$;

COMMENT ON TABLE public.permissions IS
    'Proposed Phase 7 permission catalog; migration is not authorized on the live database.';
COMMENT ON TABLE public.role_permissions IS
    'Proposed Phase 7 RBAC mapping; no existing user role assignments are changed.';
COMMENT ON TABLE public.auth_refresh_tokens IS
    'Proposed Phase 7 hashed refresh-token store; raw tokens are never persisted.';

COMMIT;

-- Rollback: disable dependent routes and retain audit/security history. Do not
-- drop permission, session, or financial objects after they contain data.
