import datetime
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status

from backend.db import get_db
from backend.middleware import get_current_user, require_role
from backend.schemas import LeaveApplySchema, AdminActionLeaveSchema

router = APIRouter(
    prefix="/api/v1/leaves",
    tags=["Leave & Time-Off Management (Prompt 7)"],
    dependencies=[Depends(get_current_user)]
)

def calculate_working_days(start_str: str, end_str: str) -> int:
    try:
        start = datetime.date.fromisoformat(start_str)
        end = datetime.date.fromisoformat(end_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Invalid date format. Expected YYYY-MM-DD."}
        )

    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "End date cannot be prior to start date."}
        )

    days = 0
    curr = start
    while curr <= end:
        if curr.weekday() < 5:  # Monday to Friday
            days += 1
        curr += datetime.timedelta(days=1)

    return max(1, days)

@router.post("/apply")
async def apply_for_leave(
    payload: LeaveApplySchema,
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 7.1: Apply for Leave (Employee):
    Form capturing leave_type (PAID, SICK, UNPAID), start_date, end_date, and leave_reason.
    Initial state: leave_status = 'PENDING'.
    """
    user_id = current_user["user_id"]
    days_count = calculate_working_days(payload.start_date, payload.end_date)

    cursor = db.cursor()
    cursor.execute("SELECT leave_balance_paid, leave_balance_sick FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    # Balance validation
    if payload.leave_type == "PAID" and (user["leave_balance_paid"] or 0) < days_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": f"Insufficient Paid Leave balance. Available: {user['leave_balance_paid']}, Requested: {days_count}."
            }
        )
    elif payload.leave_type == "SICK" and (user["leave_balance_sick"] or 0) < days_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": f"Insufficient Sick Leave balance. Available: {user['leave_balance_sick']}, Requested: {days_count}."
            }
        )

    cursor.execute("""
        INSERT INTO leave_requests (user_id, leave_type, start_date, end_date, leave_reason, leave_status)
        VALUES (%s, %s, %s, %s, %s, 'PENDING') RETURNING leave_id
    """, (user_id, payload.leave_type, payload.start_date, payload.end_date, payload.leave_reason.strip()))
    db.commit()
    leave_id = cursor.fetchone()["leave_id"]

    return {
        "success": True,
        "message": f"Leave application for {days_count} day(s) submitted to HR approval queue.",
        "data": {
            "leave_id": leave_id,
            "user_id": user_id,
            "leave_type": payload.leave_type,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "leave_reason": payload.leave_reason,
            "leave_status": "PENDING"
        }
    }

@router.get("/my-requests")
async def get_my_leave_requests(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Fetch all personal leave applications submitted by employee.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT leave_id, user_id, leave_type, start_date, end_date, leave_reason, leave_status, admin_comment, created_at
        FROM leave_requests
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (current_user["user_id"],))
    rows = cursor.fetchall()

    requests = [
        {
            "leave_id": r["leave_id"],
            "user_id": r["user_id"],
            "leave_type": r["leave_type"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "leave_reason": r["leave_reason"],
            "leave_status": r["leave_status"],
            "admin_comment": r["admin_comment"],
            "created_at": r["created_at"]
        }
        for r in rows
    ]

    return {"success": True, "count": len(requests), "leave_requests": requests}

@router.get("/admin/queue")
async def get_admin_leave_queue(
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 7.2: Leave Approval Queue (Admin/HR):
    Construct an admin dashboard queue showing all pending requests.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT l.leave_id, l.user_id, u.employee_id, u.first_name, u.last_name, u.email, u.department,
               u.leave_balance_paid, u.leave_balance_sick,
               l.leave_type, l.start_date, l.end_date, l.leave_reason, l.leave_status, l.created_at
        FROM leave_requests l
        JOIN users u ON l.user_id = u.id
        WHERE l.leave_status = 'PENDING'
        ORDER BY l.created_at ASC
    """)
    rows = cursor.fetchall()

    queue = [
        {
            "leave_id": r["leave_id"],
            "user_id": r["user_id"],
            "employee_id": r["employee_id"],
            "employee_name": f"{r['first_name']} {r['last_name']}",
            "email": r["email"],
            "department": r["department"],
            "paid_balance": r["leave_balance_paid"],
            "sick_balance": r["leave_balance_sick"],
            "leave_type": r["leave_type"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "leave_reason": r["leave_reason"],
            "leave_status": r["leave_status"],
            "created_at": r["created_at"]
        }
        for r in rows
    ]

    return {"success": True, "count": len(queue), "pending_queue": queue}

@router.patch("/admin/action/{leave_id}")
async def action_leave_request(
    leave_id: int,
    payload: AdminActionLeaveSchema,
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 7.2: Updating the state sets leave_status to APPROVED or REJECTED
    with admin_comment and updates employee availability in the dashboard calendar.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT l.leave_id, l.user_id, l.leave_type, l.start_date, l.end_date, l.leave_status,
               u.leave_balance_paid, u.leave_balance_sick
        FROM leave_requests l
        JOIN users u ON l.user_id = u.id
        WHERE l.leave_id = %s
    """, (leave_id,))
    leave = cursor.fetchone()

    if not leave:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Leave request not found."}
        )

    days_count = calculate_working_days(leave["start_date"], leave["end_date"])

    # Auto-deduct leave balance if approved
    if payload.leave_status == "APPROVED" and leave["leave_status"] != "APPROVED":
        if leave["leave_type"] == "PAID":
            new_bal = max(0, (leave["leave_balance_paid"] or 18) - days_count)
            cursor.execute("UPDATE users SET leave_balance_paid = %s WHERE id = %s", (new_bal, leave["user_id"]))
        elif leave["leave_type"] == "SICK":
            new_bal = max(0, (leave["leave_balance_sick"] or 10) - days_count)
            cursor.execute("UPDATE users SET leave_balance_sick = %s WHERE id = %s", (new_bal, leave["user_id"]))

    comment = payload.admin_comment or f"Decision {payload.leave_status} by HR Admin ({admin_user.get('email')})"

    cursor.execute("""
        UPDATE leave_requests 
        SET leave_status = %s, admin_comment = %s, updated_at = CURRENT_TIMESTAMP
        WHERE leave_id = %s
    """, (payload.leave_status, comment, leave_id))
    db.commit()

    return {
        "success": True,
        "message": f"Leave #{leave_id} marked as {payload.leave_status}.",
        "data": {
            "leave_id": leave_id,
            "leave_status": payload.leave_status,
            "admin_comment": comment
        }
    }
