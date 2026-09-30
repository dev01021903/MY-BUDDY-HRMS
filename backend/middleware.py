from fastapi import Header, HTTPException, status, Depends
from typing import List, Union
import datetime
import psycopg2
import psycopg2.extras
import jwt

from backend.security import decode_access_token
from backend.db import get_db_connection

# Inactivity timeout: 120 seconds (2 minutes)
INACTIVITY_TIMEOUT_SECONDS = 120
MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_MINUTES = 15

async def get_current_user(authorization: Union[str, None] = Header(default=None)):
    """
    FastAPI dependency that extracts and validates the Bearer JWT token from the Authorization header.
    Enforces token validity and 2-minute inactivity expiration against database session.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Access denied. No authentication token provided."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Access denied. Malformed token format. Expected: Bearer <token>"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    try:
        payload = decode_access_token(token)
        if "user_id" not in payload or "role" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"success": False, "message": "Invalid token payload structure."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload["user_id"]

        # Check server-side 2-minute inactivity
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, last_activity, role, is_email_verified FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"success": False, "message": "User session no longer exists."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user["last_activity"]:
            try:
                last_act = datetime.datetime.fromisoformat(user["last_activity"])
                if last_act.tzinfo is None:
                    last_act = last_act.replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                elapsed_seconds = (now - last_act).total_seconds()

                if elapsed_seconds > INACTIVITY_TIMEOUT_SECONDS:
                    conn.close()
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "success": False,
                            "inactivity_logout": True,
                            "message": "Session expired due to 2 minutes of inactivity. Please log in again."
                        },
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except (ValueError, TypeError):
                pass

        # Update last_activity to current timestamp for active sessions
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("UPDATE users SET last_activity = %s WHERE id = %s", (now_str, user_id))
        conn.commit()
        conn.close()

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Session token has expired. Please log in again."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Invalid authentication token signature."},
            headers={"WWW-Authenticate": "Bearer"},
        )

def require_role(allowed_roles: Union[str, List[str]]):
    """
    FastAPI dependency factory enforcing Role-Based Access Control (RBAC).
    Example: Depends(require_role("HR_ADMIN"))
    """
    roles = [allowed_roles] if isinstance(allowed_roles, str) else allowed_roles

    async def role_checker(current_user: dict = Depends(get_current_user)):
        user_role = current_user.get("role")
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": f"Forbidden: Access restricted to [{', '.join(roles)}]. Current role is [{user_role}].",
                    "required_role": roles,
                    "user_role": user_role
                }
            )
        return current_user

    return role_checker
