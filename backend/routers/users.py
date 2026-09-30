from fastapi import APIRouter, Depends, HTTPException, status
import psycopg2
import psycopg2.extras

from backend.db import get_db
from backend.middleware import get_current_user

router = APIRouter(
    prefix="/api/users",
    tags=["User Data Access"],
    dependencies=[Depends(get_current_user)]
)

@router.get("")
@router.get("/")
async def list_accessible_users(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Role-based user list:
    - HR_ADMIN: Sees ALL employee records.
    - EMPLOYEE: Sees ONLY their own record.
    """
    cursor = db.cursor()

    if current_user.get("role") == "HR_ADMIN":
        cursor.execute("""
            SELECT id, employee_id, first_name, last_name, email, role, is_verified, created_at, failed_login_attempts, locked_until 
            FROM users 
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
    else:
        # EMPLOYEE: strictly scoped to self
        cursor.execute("""
            SELECT id, employee_id, first_name, last_name, email, role, is_verified, created_at, failed_login_attempts, locked_until 
            FROM users 
            WHERE id = %s
        """, (current_user["user_id"],))
        rows = cursor.fetchall()

    users = [
        {
            "id": r["id"],
            "employee_id": r["employee_id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "email": r["email"],
            "role": r["role"],
            "is_verified": bool(r["is_verified"]),
            "is_locked": bool(r["locked_until"]),
            "created_at": r["created_at"]
        }
        for r in rows
    ]

    return {
        "success": True,
        "role": current_user.get("role"),
        "count": len(users),
        "users": users
    }

@router.get("/{user_id}")
async def get_user_by_id(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Role-based single user lookup:
    - HR_ADMIN: Can view ANY employee's record.
    - EMPLOYEE: Can ONLY view their own record (user_id == current_user.id). Attempts to view other employees return 403 Forbidden.
    """
    is_admin = current_user.get("role") == "HR_ADMIN"
    is_self = current_user.get("user_id") == user_id

    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "message": "Access Denied: Regular employees are strictly restricted to viewing their own user-scoped records.",
                "requested_user_id": user_id,
                "authenticated_user_id": current_user.get("user_id")
            }
        )

    cursor = db.cursor()
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, role, is_verified, failed_login_attempts, locked_until, created_at 
        FROM users WHERE id = %s
    """, (user_id,))
    user = cursor.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Employee record not found."}
        )

    return {
        "success": True,
        "access_level": "HR_ADMIN_FULL" if is_admin else "USER_SCOPED_SELF",
        "user": {
            "id": user["id"],
            "employee_id": user["employee_id"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "email": user["email"],
            "role": user["role"],
            "is_verified": bool(user["is_verified"]),
            "is_locked": bool(user["locked_until"]),
            "failed_attempts": user["failed_login_attempts"],
            "created_at": user["created_at"]
        }
    }
