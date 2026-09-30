import datetime
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional

from backend.db import get_db
from backend.middleware import get_current_user, require_role

router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Control & Context Switcher (Prompt 4.2)"],
    dependencies=[Depends(require_role("HR_ADMIN"))]
)

@router.get("/overview")
async def get_admin_overview(db: psycopg2.extensions.connection = Depends(get_db)):
    """
    Prompt 4.2: Company-wide metrics & dashboard counts.
    """
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_email_verified = 1")
    verified_users = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM attendance WHERE approval_status IN ('PENDING_ADMIN_APPROVAL', 'REJECTED')")
    flagged_att = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM leave_requests WHERE leave_status = 'PENDING'")
    pending_leaves = cursor.fetchone()["count"]

    return {
        "success": True,
        "data": {
            "totalUsers": total_users,
            "verifiedUsers": verified_users,
            "flaggedAttendance": flagged_att,
            "pendingLeaves": pending_leaves
        }
    }

@router.get("/employees")
async def get_employees_directory(
    search: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 4.2: Interactive Employee Card Directory with search and filters.
    """
    cursor = db.cursor()
    query = """
        SELECT id as user_id, id, employee_id, first_name, last_name, email, role, phone, address,
               profile_picture_url, job_title, department, joining_date, documents_url,
               salary_base, salary_allowances, salary_deductions, net_salary,
               leave_balance_paid, leave_balance_sick, is_email_verified,
               failed_login_attempts, locked_until, created_at
        FROM users WHERE 1=1
    """
    params = []

    if search:
        query += " AND (first_name LIKE %s OR last_name LIKE %s OR email LIKE %s OR employee_id LIKE %s)"
        s = f"%{search.strip()}%"
        params.extend([s, s, s, s])

    if role:
        query += " AND role = %s"
        params.append(role)

    query += " ORDER BY id ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()

    now = datetime.datetime.utcnow()
    employees = []

    for r in rows:
        is_locked = False
        if r["locked_until"]:
            try:
                locked_time = datetime.datetime.fromisoformat(r["locked_until"])
                if locked_time > now:
                    is_locked = True
            except ValueError:
                pass

        employees.append({
            "user_id": r["user_id"],
            "id": r["id"],
            "employee_id": r["employee_id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "full_name": f"{r['first_name']} {r['last_name']}",
            "email": r["email"],
            "role": r["role"],
            "phone": r["phone"] or "Not provided",
            "address": r["address"] or "Not provided",
            "profile_picture_url": r["profile_picture_url"],
            "job_title": r["job_title"],
            "department": r["department"],
            "joining_date": r["joining_date"],
            "documents_url": r["documents_url"],
            "salary_base": float(r["salary_base"] or 0),
            "salary_allowances": float(r["salary_allowances"] or 0),
            "salary_deductions": float(r["salary_deductions"] or 0),
            "net_salary": float(r["net_salary"] or 0),
            "leave_balance_paid": r["leave_balance_paid"],
            "leave_balance_sick": r["leave_balance_sick"],
            "is_email_verified": bool(r["is_email_verified"]),
            "is_verified": bool(r["is_email_verified"]),
            "is_locked": is_locked
        })

    return {"success": True, "count": len(employees), "employees": employees}

@router.get("/employees/{target_user_id}/context-view")
async def get_employee_context_view(
    target_user_id: int,
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 4.2: Global Employee Context Switcher:
    Allows HR Officers to inspect any individual employee's view
    with read/edit capabilities (Profile, Attendance, Leaves, Payroll).
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, role, phone, address,
               profile_picture_url, job_title, department, joining_date, documents_url,
               salary_base, salary_allowances, salary_deductions, net_salary,
               leave_balance_paid, leave_balance_sick, is_email_verified, created_at
        FROM users WHERE id = %s
    """, (target_user_id,))
    u = cursor.fetchone()

    if not u:
        raise HTTPException(status_code=404, detail="Employee not found.")

    # Recent attendance logs
    cursor.execute("""
        SELECT attendance_id, attendance_date, check_in_time, check_out_time,
               is_within_geofence, attendance_status, approval_status, admin_comment
        FROM attendance WHERE user_id = %s ORDER BY attendance_date DESC LIMIT 10
    """, (target_user_id,))
    att_rows = cursor.fetchall()

    # Leave requests
    cursor.execute("""
        SELECT leave_id, leave_type, start_date, end_date, leave_reason, leave_status, admin_comment
        FROM leave_requests WHERE user_id = %s ORDER BY created_at DESC
    """, (target_user_id,))
    leave_rows = cursor.fetchall()

    # Payroll records
    cursor.execute("""
        SELECT payroll_id, salary_base, salary_allowances, salary_deductions, net_salary, updated_at
        FROM payroll WHERE user_id = %s ORDER BY payroll_id DESC
    """, (target_user_id,))
    pay_rows = cursor.fetchall()

    return {
        "success": True,
        "context_user": {
            "user_id": u["id"],
            "employee_id": u["employee_id"],
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "email": u["email"],
            "role": u["role"],
            "phone": u["phone"],
            "address": u["address"],
            "profile_picture_url": u["profile_picture_url"],
            "job_title": u["job_title"],
            "department": u["department"],
            "joining_date": u["joining_date"],
            "documents_url": u["documents_url"],
            "salary_base": float(u["salary_base"] or 0),
            "salary_allowances": float(u["salary_allowances"] or 0),
            "salary_deductions": float(u["salary_deductions"] or 0),
            "net_salary": float(u["net_salary"] or 0),
            "leave_balance_paid": u["leave_balance_paid"],
            "leave_balance_sick": u["leave_balance_sick"],
            "is_email_verified": bool(u["is_email_verified"])
        },
        "attendance_logs": [dict(r) for r in att_rows],
        "leave_requests": [dict(r) for r in leave_rows],
        "payroll_records": [dict(r) for r in pay_rows]
    }

@router.patch("/employees/{target_user_id}/unlock")
async def unlock_employee(target_user_id: int, db: psycopg2.extensions.connection = Depends(get_db)):
    """
    Unlocks an account that was locked after 3 failed login attempts.
    """
    cursor = db.cursor()
    cursor.execute("""
        UPDATE users 
        SET failed_login_attempts = 0, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (target_user_id,))
    db.commit()

    return {"success": True, "message": f"Employee #{target_user_id} account unlocked."}
