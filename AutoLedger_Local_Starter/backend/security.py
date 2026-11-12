import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.extras import RealDictCursor

from backend.database import get_connection

JWT_SECRET = os.getenv("AUTH_SECRET_KEY", "").strip()
if len(JWT_SECRET) < 32:
    raise RuntimeError("AUTH_SECRET_KEY must be configured with at least 32 characters in the local environment.")
JWT_ALGORITHM = "HS256"
TOKEN_HOURS = 8
bearer_scheme = HTTPBearer(auto_error=False)

ACTIVE_BUSINESS_ROLES = frozenset({
    "Super Admin",
    "Admin",
    "Business Owner",
    "Manager",
    "Accountant",
    "Staff",
    "Viewer",
})

LEGACY_ROLES = frozenset({
    "Dealer",
    "Inspector",
    "Owner/Viewer",
    "Verification User",
})

ROLE_PERMISSION_DEFAULTS: dict[str, frozenset[str]] = {
    "Super Admin": frozenset({"*"}),
    "Admin": frozenset({
        "vehicles.read", "owners.read",
        "history.read", "verification.read",
        "customers.read", "customers.manage", "suppliers.read",
        "suppliers.manage", "inventory.read", "inventory.manage",
        "purchases.read", "purchases.manage", "sales.read", "sales.manage",
        "payments.read", "payments.manage", "financial.read",
        "reports.operational", "reports.financial", "invoices.read",
    }),
    "Business Owner": frozenset({
        "vehicles.read", "owners.read", "history.read", "verification.read",
        "customers.read", "customers.manage",
        "suppliers.read", "suppliers.manage", "inventory.read", "inventory.manage",
        "purchases.read", "purchases.manage", "sales.read", "sales.manage",
        "payments.read", "payments.manage", "financial.read",
        "reports.operational", "reports.financial", "invoices.read",
    }),
    "Manager": frozenset({
        "vehicles.read", "owners.read", "history.read", "verification.read",
        "customers.read", "customers.manage", "suppliers.read",
        "suppliers.manage", "inventory.read", "inventory.manage", "purchases.read",
        "purchases.manage", "sales.read", "sales.manage", "payments.read",
        "reports.operational",
    }),
    "Accountant": frozenset({
        "customers.read", "suppliers.read", "purchases.read", "sales.read",
        "payments.read", "payments.manage", "financial.read",
        "reports.financial", "invoices.read",
    }),
    "Staff": frozenset({
        "vehicles.read", "owners.read", "history.read", "verification.read",
    }),
    "Viewer": frozenset({
        "vehicles.read", "owners.read", "history.read", "verification.read",
    }),
}


def resolve_permissions(role_name: str, persisted_permissions=None) -> frozenset[str]:
    if role_name not in ACTIVE_BUSINESS_ROLES:
        return frozenset()
    ceiling = ROLE_PERMISSION_DEFAULTS[role_name]
    if role_name == "Super Admin":
        return ceiling
    if persisted_permissions is None:
        return ceiling
    return ceiling.intersection(persisted_permissions)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at, "ver": token_version},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to access this resource.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.user_id, u.full_name, u.email, u.role_id, r.role_name,
                       COALESCE((to_jsonb(u)->>'token_version')::INTEGER, 0) AS token_version
                FROM users u
                JOIN roles r ON r.role_id = u.role_id
                WHERE u.user_id = %s AND u.is_active = TRUE
                """,
                (user_id,),
            )
            user = cur.fetchone()
        if user is None:
            raise unauthorized
        token_version = int(user["token_version"])
        if int(payload.get("ver", 0)) != token_version:
            raise unauthorized
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT to_regclass('public.role_permissions') IS NOT NULL AS installed")
            permissions_installed = cur.fetchone()["installed"]
            if permissions_installed and user["role_name"] in ACTIVE_BUSINESS_ROLES:
                cur.execute(
                    """
                    SELECT permission_key
                    FROM role_permissions
                    WHERE role_id = %s
                    ORDER BY permission_key
                    """,
                    (user["role_id"],),
                )
                persisted_permissions = [row["permission_key"] for row in cur.fetchall()]
                permissions = sorted(resolve_permissions(user["role_name"], persisted_permissions))
            else:
                permissions = sorted(resolve_permissions(user["role_name"]))
        result = dict(user)
        result["permissions"] = permissions
        return result
    finally:
        conn.close()


def require_permissions(*required_permissions: str):
    def dependency(user=Depends(get_current_user)):
        return authorize_permissions(user, *required_permissions)

    return dependency


def get_business_context(
    business_id: int = Header(alias="X-Business-ID", gt=0),
    user=Depends(get_current_user),
):
    connection = get_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT to_regclass('public.business_memberships') IS NOT NULL
                   AND to_regclass('public.businesses') IS NOT NULL AS installed
                """
            )
            if not cursor.fetchone()["installed"]:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Business membership schema is not installed.",
                )
            cursor.execute(
                """
                SELECT r.role_name, b.business_id
                FROM business_memberships bm
                JOIN businesses b ON b.business_id = bm.business_id
                JOIN roles r ON r.role_id = bm.role_id
                WHERE bm.user_id = %s
                  AND bm.business_id = %s
                  AND bm.is_active = TRUE
                  AND b.is_active = TRUE
                """,
                (user["user_id"], business_id),
            )
            membership = cursor.fetchone()
            if membership is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not an active member of the selected business.",
                )

            role_name = membership["role_name"]
            if role_name not in ACTIVE_BUSINESS_ROLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The selected business membership has no active application role.",
                )
            cursor.execute("SELECT to_regclass('public.role_permissions') IS NOT NULL AS installed")
            persisted_permissions = None
            if cursor.fetchone()["installed"]:
                cursor.execute(
                    """
                    SELECT permission_key
                    FROM role_permissions
                    WHERE role_id = (
                        SELECT role_id FROM business_memberships
                        WHERE user_id = %s AND business_id = %s AND is_active = TRUE
                    )
                    """,
                    (user["user_id"], business_id),
                )
                persisted_permissions = [row["permission_key"] for row in cursor.fetchall()]

            result = dict(user)
            result["business_id"] = business_id
            result["role_name"] = role_name
            result["permissions"] = sorted(resolve_permissions(role_name, persisted_permissions))
            return result
    finally:
        connection.close()


def require_business_permissions(*required_permissions: str):
    def dependency(user=Depends(get_business_context)):
        return authorize_permissions(user, *required_permissions)

    return dependency


def has_permission(user, permission: str) -> bool:
    permissions = set(user.get("permissions", ()))
    return "*" in permissions or permission in permissions


def authorize_platform_admin(user):
    if user.get("role_name") != "Super Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Super Admin may change globally shared vehicle or history records.",
        )
    return user


def require_platform_admin():
    def dependency(user=Depends(get_current_user)):
        return authorize_platform_admin(user)

    return dependency


def authorize_permissions(user, *required_permissions: str):
    permissions = set(user.get("permissions", ()))
    if user.get("role_name") in LEGACY_ROLES or (
        "*" not in permissions and not set(required_permissions).issubset(permissions)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not have permission to perform this action.",
        )
    return user