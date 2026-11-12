import logging
import hashlib
import bcrypt
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from psycopg2.extras import RealDictCursor

from backend.database import get_connection
from backend.security import create_access_token, get_current_user, require_roles

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


class Registration(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class AdminUserCreate(Registration):
    role: str = Field(pattern="^(Admin|Inspector|Dealer|Owner/Viewer)$")


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(Admin|Inspector|Dealer|Owner/Viewer)$")
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update_fields(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Provide a role or active status to update.")
        return self


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
def login(credentials: Credentials):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.user_id, u.full_name, u.email, u.password_hash, r.role_name
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

        return {
            "access_token": create_access_token(user["user_id"]),
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
                cur.execute("SELECT role_id FROM roles WHERE role_name='Owner/Viewer'")
                role = cur.fetchone()
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


@router.get("/users")
def list_users(user=Depends(require_roles("Admin"))):
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
def create_user(user_data: AdminUserCreate, admin=Depends(require_roles("Admin"))):
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
def get_user(user_id: int, admin=Depends(require_roles("Admin"))):
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
def update_user(user_id: int, user_data: AdminUserUpdate, admin=Depends(require_roles("Admin"))):
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