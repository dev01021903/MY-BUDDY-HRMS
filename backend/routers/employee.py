import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status

from backend.db import get_db
from backend.middleware import get_current_user

router = APIRouter(
    prefix="/api/employee",
    tags=["Employee Dashboard (Prompt 4.1)"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/dashboard")
async def get_employee_dashboard(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 4.1: Employee Dashboard:
    Display quick-access metrics for Personal Profile, Attendance logs,
    active Leave Requests, and recent announcements.
    """
    user_id = current_user["user_id"]
    cursor = db.cursor()

    # 1. Profile
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, role, phone, address, profile_picture_url,
               job_title, department, joining_date, documents_url, salary_base, net_salary,
               leave_balance_paid, leave_balance_sick, is_email_verified
        FROM users WHERE id = %s
    """, (user_id,))
    u = cursor.fetchone()

    # 2. Recent Attendance logs (today & latest 5)
    cursor.execute("""
        SELECT attendance_id, attendance_date, check_in_time, check_out_time,
               is_within_geofence, attendance_status, approval_status, admin_comment
        FROM attendance WHERE user_id = %s ORDER BY attendance_date DESC, attendance_id DESC LIMIT 5
    """, (user_id,))
    att_rows = cursor.fetchall()

    # 3. Active Leave Requests
    cursor.execute("""
        SELECT leave_id, leave_type, start_date, end_date, leave_reason, leave_status, admin_comment, created_at
        FROM leave_requests WHERE user_id = %s ORDER BY created_at DESC LIMIT 5
    """, (user_id,))
    leave_rows = cursor.fetchall()

    # 4. Recent Announcements
    cursor.execute("SELECT id, title, message, posted_at FROM announcements ORDER BY posted_at DESC LIMIT 3")
    announcement_rows = cursor.fetchall()

    return {
        "success": True,
        "data": {
            "profile": {
                "user_id": u["id"],
                "employee_id": u["employee_id"],
                "first_name": u["first_name"],
                "last_name": u["last_name"],
                "full_name": f"{u['first_name']} {u['last_name']}",
                "email": u["email"],
                "role": u["role"],
                "job_title": u["job_title"],
                "department": u["department"],
                "joining_date": u["joining_date"],
                "documents_url": u["documents_url"],
                "salary_base": float(u["salary_base"] or 0),
                "net_salary": float(u["net_salary"] or 0),
                "leave_balance_paid": u["leave_balance_paid"],
                "leave_balance_sick": u["leave_balance_sick"],
                "is_email_verified": bool(u["is_email_verified"])
            },
            "recent_attendance": [dict(r) for r in att_rows],
            "active_leave_requests": [dict(r) for r in leave_rows],
            "announcements": [dict(r) for r in announcement_rows],
            "securityContext": {
                "scope": "USER_RESTRICTED",
                "authorizedUserId": user_id,
                "role": current_user["role"]
            }
        }
    }
