import logging
import hashlib
import os
import secrets
import bcrypt
import psycopg2
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg2.extras import RealDictCursor

from backend.database import get_connection
from backend.security import (
    ACTIVE_BUSINESS_ROLES,
    ROLE_PERMISSION_DEFAULTS,
    create_access_token,
    get_current_user,
    resolve_permissions,
    require_permissions,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def hash_password(password: str) -> str:
    prehashed = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
    return bcrypt.hashpw(prehashed, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    prehashed = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
    try:
        return bcrypt.checkpw(prehashed, password_hash.encode("ascii"))
    except ValueError:
        return False


class Credentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class AdminBootstrap(Credentials):
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("password")
    @classmethod
    def require_strong_password(cls, value):
        if len(value) < 12:
            raise ValueError("Password must contain at least 12 characters.")
        return value


class Registration(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def require_strong_password(cls, value):
        if len(value) < 12:
            raise ValueError("Password must contain at least 12 characters.")
        return value


class AdminUserCreate(Registration):
    role: str = Field(pattern="^(Super Admin|Admin|Business Owner|Manager|Accountant|Staff|Viewer)$")


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(Super Admin|Admin|Business Owner|Manager|Accountant|Staff|Viewer)$")
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update_fields(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Provide a role or active status to update.")
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def require_new_password(self):
        if self.current_password == self.new_password:
            raise ValueError("The new password must differ from the current password.")
        return self


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def strip_name(self):
        self.full_name = self.full_name.strip()
        if not self.full_name:
            raise ValueError("full_name cannot be blank.")
        return self


class RolePermissionsUpdate(BaseModel):
    permission_keys: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_permissions(self):
        if len(self.permission_keys) != len(set(self.permission_keys)):
            raise ValueError("permission_keys must be unique.")
        return self


REFRESH_TOKEN_DAYS = 14
REFRESH_COOKIE_NAME = "autoledger_refresh"
REFRESH_COOKIE_SECURE = os.getenv("APP_ENV", "development").casefold() == "production"


def _new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return token, digest


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite="strict",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite="strict",
        path="/api/auth",
    )


def _refresh_schema_available(cursor) -> bool:
    cursor.execute("SELECT to_regclass('public.auth_refresh_tokens') IS NOT NULL AS installed")
    return bool(cursor.fetchone()["installed"])


def _issue_refresh_token(cursor, user_id: int) -> str:
    token, token_hash = _new_refresh_token()
    cursor.execute(
        """
        INSERT INTO auth_refresh_tokens (token_hash, user_id, expires_at)
        VALUES (%s, %s, %s)
        """,
        (token_hash, user_id, datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)),
    )
    return token


@router.get("/status")
def auth_status():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM users u JOIN roles r USING (role_id)
                    WHERE r.role_name = 'Admin' AND u.password_hash IS NOT NULL
                ) AS initialized
                """
            )
            initialized = cur.fetchone()["initialized"]
            if initialized:
                setup_account = None
            else:
                cur.execute(
                    "SELECT email, full_name FROM users u JOIN roles r USING(role_id) WHERE r.role_name='Admin' ORDER BY user_id LIMIT 1"
                )
                setup_account = cur.fetchone()
        return {"initialized": initialized, "setup_account": setup_account}
    finally:
        conn.close()


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED)
def bootstrap_admin(credentials: AdminBootstrap):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT u.user_id, u.email
                    FROM users u JOIN roles r USING (role_id)
                    WHERE r.role_name = 'Admin' AND u.email = %s AND u.password_hash IS NULL
                    FOR UPDATE OF u
                    """,
                    (credentials.email.lower(),),
                )
                admin = cur.fetchone()
                if admin is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Admin setup is unavailable for this account. Check the email or sign in.",
                    )

                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM users u JOIN roles r USING (role_id)
                        WHERE r.role_name = 'Admin' AND u.password_hash IS NOT NULL
                    ) AS admin_initialized
                    """
                )
                if cur.fetchone()["admin_initialized"]:
                    raise HTTPException(status_code=409, detail="Admin setup has already been completed.")

                hashed = hash_password(credentials.password)
                cur.execute(
                    "UPDATE users SET full_name = %s, password_hash = %s WHERE user_id = %s",
                    (credentials.full_name, hashed, admin["user_id"]),
                )
        return {"message": "Admin account initialized. Sign in with your new password."}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Admin bootstrap failed")
        raise
    finally:
        conn.close()


@router.post("/login")
def login(credentials: Credentials, response: Response):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT u.user_id, u.full_name, u.email, u.password_hash,
                           COALESCE((to_jsonb(u)->>'token_version')::INTEGER, 0) AS token_version,
                           r.role_name
                    FROM users u JOIN roles r USING (role_id)
                    WHERE LOWER(u.email) = LOWER(%s) AND u.is_active = TRUE
                    """,
                    (credentials.email,),
                )
                user = cur.fetchone()
                if (
                    user is None
                    or user["password_hash"] is None
                    or not verify_password(credentials.password, user["password_hash"])
                ):
                    raise HTTPException(status_code=401, detail="Email or password is incorrect.")

                refresh_token = None
                if _refresh_schema_available(cur):
                    refresh_token = _issue_refresh_token(cur, user["user_id"])

        if refresh_token:
            _set_refresh_cookie(response, refresh_token)

        return {
            "access_token": create_access_token(user["user_id"], user["token_version"]),
            "token_type": "bearer",
            "user": {
                "user_id": user["user_id"],
                "full_name": user["full_name"],
                "email": user["email"],
                "role": user["role_name"],
            },
        }
    finally:
        conn.close()


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(registration: Registration):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT role_id FROM roles
                    WHERE role_name = 'Viewer'
                    LIMIT 1
                    """
                )
                role = cur.fetchone()
                if role is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Viewer registration is unavailable until the approved seven-role migration is installed.",
                    )
                password_hash = hash_password(registration.password)
                cur.execute(
                    """
                    INSERT INTO users (role_id, full_name, email, password_hash)
                    VALUES (%s, %s, %s, %s)
                    RETURNING user_id, full_name, email
                    """,
                    (role["role_id"], registration.full_name, registration.email.lower(), password_hash),
                )
                return {"user": cur.fetchone(), "message": "Account created. You can now sign in."}
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    finally:
        conn.close()


@router.get("/me")
def current_profile(user=Depends(get_current_user)):
    return dict(user)


@router.get("/businesses")
def list_business_memberships(user=Depends(get_current_user)):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT to_regclass('public.business_memberships') IS NOT NULL
                   AND to_regclass('public.businesses') IS NOT NULL AS installed
                """
            )
            if not cur.fetchone()["installed"]:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Business membership schema is not installed.",
                )
            cur.execute(
                """
                SELECT b.business_id, b.business_name, r.role_id, r.role_name
                FROM business_memberships bm
                JOIN businesses b ON b.business_id = bm.business_id
                JOIN roles r ON r.role_id = bm.role_id
                WHERE bm.user_id = %s
                  AND bm.is_active = TRUE
                  AND b.is_active = TRUE
                ORDER BY b.business_name, b.business_id
                """,
                (user["user_id"],),
            )
            businesses = cur.fetchall()
            cur.execute("SELECT to_regclass('public.role_permissions') IS NOT NULL AS installed")
            permissions_installed = cur.fetchone()["installed"]
            for business in businesses:
                persisted_permissions = None
                if permissions_installed:
                    cur.execute(
                        "SELECT permission_key FROM role_permissions WHERE role_id = %s",
                        (business["role_id"],),
                    )
                    persisted_permissions = [row["permission_key"] for row in cur.fetchall()]
                business["permissions"] = sorted(
                    resolve_permissions(business["role_name"], persisted_permissions)
                )
                del business["role_id"]
            return {"businesses": businesses}
    finally:
        conn.close()


@router.patch("/me")
def update_profile(profile: ProfileUpdate, user=Depends(get_current_user)):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute(
                    """
                    UPDATE users SET full_name = %s
                    WHERE user_id = %s AND is_active = TRUE
                    RETURNING user_id, full_name, email
                    """,
                    (profile.full_name, user["user_id"]),
                )
                updated = cur.fetchone()
                if updated is None:
                    raise HTTPException(status_code=401, detail="Your account is no longer active.")
                updated["role_name"] = user["role_name"]
                updated["permissions"] = user.get("permissions", [])
                return {"user": dict(updated)}
    finally:
        conn.close()


@router.post("/password")
def change_password(payload: PasswordChange, user=Depends(get_current_user)):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT password_hash,
                           COALESCE((to_jsonb(u)->>'token_version')::INTEGER, 0) AS token_version,
                           to_jsonb(u) ? 'token_version' AS versioning_enabled
                    FROM users u WHERE user_id = %s AND is_active = TRUE
                    FOR UPDATE
                    """,
                    (user["user_id"],),
                )
                account = cur.fetchone()
                if account is None or not verify_password(payload.current_password, account["password_hash"] or ""):
                    raise HTTPException(status_code=400, detail="Current password is incorrect.")
                if not account["versioning_enabled"]:
                    raise HTTPException(
                        status_code=503,
                        detail="Password changes require the separately approved authentication migration.",
                    )

                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user["user_id"]),))
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s, token_version = token_version + 1
                    WHERE user_id = %s
                    """,
                    (hash_password(payload.new_password), user["user_id"]),
                )
                if _refresh_schema_available(cur):
                    cur.execute(
                        """
                        UPDATE auth_refresh_tokens
                        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                        WHERE user_id = %s AND revoked_at IS NULL
                        """,
                        (user["user_id"],),
                    )
        return {"message": "Password changed. Sign in again to continue."}
    finally:
        conn.close()


@router.post("/refresh")
def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    unauthorized = HTTPException(
        status_code=401,
        detail="Refresh session is invalid or expired. Sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not refresh_token:
        raise unauthorized

    token_hash = hashlib.sha256(refresh_token.encode("ascii")).hexdigest()
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if not _refresh_schema_available(cur):
                    raise HTTPException(
                        status_code=503,
                        detail="Refresh sessions require the separately approved authentication migration.",
                    )
                cur.execute(
                    """
                    SELECT t.user_id, t.expires_at, t.revoked_at,
                           u.full_name, u.email, u.is_active, r.role_name,
                           COALESCE((to_jsonb(u)->>'token_version')::INTEGER, 0) AS token_version
                    FROM auth_refresh_tokens t
                    JOIN users u USING (user_id)
                    JOIN roles r USING (role_id)
                    WHERE t.token_hash = %s
                    FOR UPDATE OF t
                    """,
                    (token_hash,),
                )
                session = cur.fetchone()
                now = datetime.now(timezone.utc)
                if (
                    session is None
                    or session["revoked_at"] is not None
                    or session["expires_at"] <= now
                    or not session["is_active"]
                ):
                    raise unauthorized

                next_token = _issue_refresh_token(cur, session["user_id"])
                next_hash = hashlib.sha256(next_token.encode("ascii")).hexdigest()
                cur.execute(
                    """
                    UPDATE auth_refresh_tokens
                    SET revoked_at = CURRENT_TIMESTAMP, replaced_by_hash = %s
                    WHERE token_hash = %s
                    """,
                    (next_hash, token_hash),
                )
        _set_refresh_cookie(response, next_token)
        return {
            "access_token": create_access_token(session["user_id"], session["token_version"]),
            "token_type": "bearer",
            "user": {
                "user_id": session["user_id"],
                "full_name": session["full_name"],
                "email": session["email"],
                "role": session["role_name"],
            },
        }
    except ValueError:
        raise unauthorized
    finally:
        conn.close()


@router.post("/logout")
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if refresh_token and _refresh_schema_available(cur):
                    token_hash = hashlib.sha256(refresh_token.encode("ascii")).hexdigest()
                    cur.execute(
                        """
                        UPDATE auth_refresh_tokens
                        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                        WHERE token_hash = %s
                        """,
                        (token_hash,),
                    )
        _clear_refresh_cookie(response)
        return {"message": "Signed out."}
    finally:
        conn.close()


@router.get("/roles")
def list_roles(admin=Depends(require_permissions("roles.manage"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _refresh_schema_available(cur):
                raise HTTPException(
                    status_code=503,
                    detail="Role administration requires the separately approved RBAC migration.",
                )
            cur.execute(
                """
                SELECT r.role_id, r.role_name, r.description,
                       COALESCE(ARRAY_AGG(rp.permission_key ORDER BY rp.permission_key)
                           FILTER (WHERE rp.permission_key IS NOT NULL), ARRAY[]::VARCHAR[]) AS permissions
                FROM roles r
                LEFT JOIN role_permissions rp USING (role_id)
                WHERE r.role_name = ANY(%s)
                GROUP BY r.role_id
                ORDER BY r.role_name
                """,
                (list(ACTIVE_BUSINESS_ROLES),),
            )
            return {"roles": cur.fetchall()}
    finally:
        conn.close()


@router.put("/roles/{role_id}/permissions")
def replace_role_permissions(
    role_id: int,
    payload: RolePermissionsUpdate,
    admin=Depends(require_permissions("roles.manage")),
):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if not _refresh_schema_available(cur):
                    raise HTTPException(
                        status_code=503,
                        detail="Role administration requires the separately approved RBAC migration.",
                    )
                cur.execute("SELECT role_name FROM roles WHERE role_id = %s FOR UPDATE", (role_id,))
                role = cur.fetchone()
                if role is None:
                    raise HTTPException(status_code=404, detail="Role not found.")
                if role["role_name"] not in ACTIVE_BUSINESS_ROLES:
                    raise HTTPException(
                        status_code=409,
                        detail="Legacy roles cannot receive new permissions. Review the legacy-role mapping first.",
                    )
                if role["role_name"] == "Super Admin" and "system.manage" not in payload.permission_keys:
                    raise HTTPException(status_code=409, detail="Super Admin must retain system.manage.")
                cur.execute(
                    "SELECT permission_key FROM permissions WHERE permission_key = ANY(%s)",
                    (payload.permission_keys,),
                )
                known = {row["permission_key"] for row in cur.fetchall()}
                unknown = set(payload.permission_keys) - known
                if unknown:
                    raise HTTPException(status_code=422, detail=f"Unknown permission keys: {sorted(unknown)}.")
                disallowed = set(payload.permission_keys) - ROLE_PERMISSION_DEFAULTS[role["role_name"]]
                if disallowed:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Permissions exceed the approved role policy: {sorted(disallowed)}.",
                    )
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(admin["user_id"]),))
                cur.execute(
                    "DELETE FROM role_permissions WHERE role_id = %s AND NOT (permission_key = ANY(%s))",
                    (role_id, payload.permission_keys),
                )
                for permission_key in payload.permission_keys:
                    cur.execute(
                        """
                        INSERT INTO role_permissions (role_id, permission_key, granted_by)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (role_id, permission_key) DO NOTHING
                        """,
                        (role_id, permission_key, admin["user_id"]),
                    )
                cur.execute(
                    """
                    SELECT ARRAY_AGG(permission_key ORDER BY permission_key) AS permissions
                    FROM role_permissions WHERE role_id = %s
                    """,
                    (role_id,),
                )
                return {"role_id": role_id, "role_name": role["role_name"], "permissions": cur.fetchone()["permissions"] or []}
    finally:
        conn.close()


@router.get("/users")
def list_users(user=Depends(require_permissions("users.manage"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.user_id, u.full_name, u.email, u.phone, u.is_active,
                       u.created_at, r.role_name
                FROM users u JOIN roles r USING (role_id)
                ORDER BY u.user_id
                """
            )
            return {"users": cur.fetchall()}
    finally:
        conn.close()


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(user_data: AdminUserCreate, admin=Depends(require_permissions("users.manage"))):
    if user_data.role == "Super Admin" and admin["role_name"] != "Super Admin":
        raise HTTPException(status_code=403, detail="Only a Super Admin may assign the Super Admin role.")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT role_id FROM roles WHERE role_name=%s FOR UPDATE", (user_data.role,))
                role = cur.fetchone()
                if role is None:
                    raise HTTPException(status_code=422, detail="Unknown account role.")
                password_hash = hash_password(user_data.password)
                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(admin["user_id"]),))
                cur.execute(
                    """
                    INSERT INTO users (role_id, full_name, email, password_hash)
                    VALUES (%s, %s, %s, %s)
                    RETURNING user_id, full_name, email
                    """,
                    (role["role_id"], user_data.full_name, user_data.email.lower(), password_hash),
                )
                return {"user": cur.fetchone(), "message": "User created."}
    except psycopg2.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    finally:
        conn.close()


@router.get("/users/{user_id}")
def get_user(user_id: int, admin=Depends(require_permissions("users.manage"))):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT u.user_id, u.full_name, u.email, u.phone, u.is_active, u.created_at, r.role_name FROM users u JOIN roles r USING(role_id) WHERE u.user_id=%s",
                (user_id,),
            )
            user = cur.fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        return {"user": user}
    finally:
        conn.close()


@router.patch("/users/{user_id}")
def update_user(user_id: int, user_data: AdminUserUpdate, admin=Depends(require_permissions("users.manage"))):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT role_id FROM roles WHERE role_name='Admin' FOR UPDATE")
                admin_role_id = cur.fetchone()["role_id"]
                cur.execute(
                    "SELECT u.user_id, u.role_id, u.is_active, r.role_name FROM users u JOIN roles r USING(role_id) WHERE u.user_id=%s FOR UPDATE OF u",
                    (user_id,),
                )
                target = cur.fetchone()
                if target is None:
                    raise HTTPException(status_code=404, detail="User not found.")
                if (
                    (target["role_name"] == "Super Admin" or user_data.role == "Super Admin")
                    and admin["role_name"] != "Super Admin"
                ):
                    raise HTTPException(status_code=403, detail="Only a Super Admin may manage Super Admin accounts.")

                updated_role_id = target["role_id"]
                updated_role_name = target["role_name"]
                if user_data.role is not None:
                    cur.execute("SELECT role_id FROM roles WHERE role_name=%s", (user_data.role,))
                    role = cur.fetchone()
                    if role is None:
                        raise HTTPException(status_code=422, detail="Unknown account role.")
                    updated_role_id = role["role_id"]
                    updated_role_name = user_data.role
                updated_is_active = user_data.is_active if user_data.is_active is not None else target["is_active"]

                loses_admin_access = (
                    target["role_id"] == admin_role_id
                    and target["is_active"]
                    and (updated_role_id != admin_role_id or not updated_is_active)
                )
                if loses_admin_access:
                    cur.execute(
                        "SELECT COUNT(*) AS remaining FROM users WHERE role_id=%s AND is_active=TRUE AND user_id<>%s",
                        (admin_role_id, user_id),
                    )
                    if cur.fetchone()["remaining"] == 0:
                        raise HTTPException(status_code=409, detail="The final active administrator cannot be demoted or deactivated.")

                if (
                    target["role_name"] == "Super Admin"
                    and target["is_active"]
                    and (updated_role_name != "Super Admin" or not updated_is_active)
                ):
                    cur.execute(
                        """
                        SELECT COUNT(*) AS remaining
                        FROM users u JOIN roles r USING (role_id)
                        WHERE r.role_name = 'Super Admin' AND u.is_active = TRUE AND u.user_id <> %s
                        """,
                        (user_id,),
                    )
                    if cur.fetchone()["remaining"] == 0:
                        raise HTTPException(status_code=409, detail="The final active Super Admin cannot be demoted or deactivated.")

                cur.execute("SELECT set_config('app.user_id', %s, true)", (str(admin["user_id"]),))
                cur.execute(
                    "UPDATE users SET role_id=%s, is_active=%s WHERE user_id=%s RETURNING user_id, full_name, email, is_active, created_at",
                    (updated_role_id, updated_is_active, user_id),
                )
                updated = dict(cur.fetchone())
                updated["role_name"] = updated_role_name
        return {"user": updated, "message": "User access updated."}
    finally:
        conn.close()