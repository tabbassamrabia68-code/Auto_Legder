import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.extras import RealDictCursor

from backend.database import get_connection

JWT_SECRET = os.getenv("AUTH_SECRET_KEY", "").strip()
if len(JWT_SECRET) < 32:
    raise RuntimeError("AUTH_SECRET_KEY must be configured with at least 32 characters in the local environment.")
JWT_ALGORITHM = "HS256"
TOKEN_HOURS = 8
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at},
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
                SELECT u.user_id, u.full_name, u.email, u.role_id, r.role_name
                FROM users u
                JOIN roles r ON r.role_id = u.role_id
                WHERE u.user_id = %s AND u.is_active = TRUE
                """,
                (user_id,),
            )
            user = cur.fetchone()
        if user is None:
            raise unauthorized
        return user
    finally:
        conn.close()


def require_roles(*allowed_roles: str):
    def dependency(user=Depends(get_current_user)):
        if user["role_name"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not have permission to perform this action.",
            )
        return user

    return dependency