import datetime
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional

from backend.db import get_db
from backend.middleware import get_current_user, require_role
from backend.utils.geofence import evaluate_geofence, OFFICE_LAT, OFFICE_LON, GEOFENCE_RADIUS_METERS
from backend.schemas import KioskCheckInSchema, KioskCheckOutSchema, AdminVerifyAttendanceSchema

router = APIRouter(
    prefix="/api/v1/attendance",
    tags=["Kiosk-Based Smart Attendance (Prompt 6)"],
    dependencies=[Depends(get_current_user)]
)

@router.post("/kiosk/check-in")
async def kiosk_check_in(
    payload: KioskCheckInSchema,
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 6.1 & 6.2: Automated Photo/Location Attendance Kiosk:
    - Captures check_in_photo_url, check_in_latitude, and check_in_longitude.
    - Evaluates distance against target office coordinates (12.9716, 77.5946).
    - If within radius: is_within_geofence = true, approval_status = 'AUTO_APPROVED', attendance_status = 'PRESENT'.
    - If outside radius: is_within_geofence = false, approval_status = 'PENDING_ADMIN_APPROVAL' for admin review.
    """
    user_id = current_user["user_id"]
    distance, is_within = evaluate_geofence(payload.check_in_latitude, payload.check_in_longitude)

    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    if is_within:
        is_geofence_val = 1
        approval_status_val = "AUTO_APPROVED"
        attendance_status_val = "PRESENT"
        comment = f"Auto-approved: Location within {GEOFENCE_RADIUS_METERS}m office geofence ({distance:.1f}m)."
    else:
        is_geofence_val = 0
        approval_status_val = "PENDING_ADMIN_APPROVAL"
        attendance_status_val = "PRESENT"
        comment = f"Flagged for HR review: Check-in coordinates ({payload.check_in_latitude:.4f}, {payload.check_in_longitude:.4f}) are {distance:.1f}m away from office."

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO attendance (
            user_id, attendance_date, check_in_time, check_in_photo_url,
            check_in_latitude, check_in_longitude, is_within_geofence,
            attendance_status, approval_status, admin_comment
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING attendance_id
    """, (
        user_id,
        today_str,
        time_str,
        payload.check_in_photo_url,
        payload.check_in_latitude,
        payload.check_in_longitude,
        is_geofence_val,
        attendance_status_val,
        approval_status_val,
        comment
    ))
    db.commit()
    attendance_id = cursor.fetchone()["attendance_id"]

    return {
        "success": True,
        "message": "Check-in recorded and auto-approved." if is_within else "Check-in recorded and flagged for HR Admin review.",
        "data": {
            "attendance_id": attendance_id,
            "user_id": user_id,
            "attendance_date": today_str,
            "check_in_time": time_str,
            "check_in_photo_url": payload.check_in_photo_url,
            "check_in_latitude": payload.check_in_latitude,
            "check_in_longitude": payload.check_in_longitude,
            "is_within_geofence": bool(is_within),
            "attendance_status": attendance_status_val,
            "approval_status": approval_status_val,
            "distance_meters": distance,
            "admin_comment": comment
        }
    }

@router.post("/kiosk/check-out")
async def kiosk_check_out(
    payload: KioskCheckOutSchema,
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 6.1: Record shift check-out timestamp.
    """
    user_id = current_user["user_id"]
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")

    cursor = db.cursor()
    cursor.execute("""
        SELECT attendance_id FROM attendance
        WHERE user_id = %s AND check_out_time IS NULL
        ORDER BY attendance_id DESC LIMIT 1
    """, (user_id,))
    active = cursor.fetchone()

    if not active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "No active check-in found to check out from."}
        )

    cursor.execute("""
        UPDATE attendance 
        SET check_out_time = %s, check_out_photo_url = %s
        WHERE attendance_id = %s
    """, (time_str, payload.check_out_photo_url, active["attendance_id"]))
    db.commit()

    return {
        "success": True,
        "message": "Check-out time recorded successfully.",
        "data": {
            "attendance_id": active["attendance_id"],
            "check_out_time": time_str
        }
    }

@router.get("/my-logs")
async def get_my_attendance_logs(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Personal attendance logs list for authenticated employee.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT attendance_id, user_id, attendance_date, check_in_time, check_out_time,
               check_in_photo_url, check_out_photo_url, check_in_latitude, check_in_longitude,
               is_within_geofence, attendance_status, approval_status, admin_comment
        FROM attendance
        WHERE user_id = %s
        ORDER BY attendance_date DESC, attendance_id DESC
    """, (current_user["user_id"],))
    rows = cursor.fetchall()

    logs = [
        {
            "attendance_id": r["attendance_id"],
            "user_id": r["user_id"],
            "attendance_date": r["attendance_date"],
            "check_in_time": r["check_in_time"],
            "check_out_time": r["check_out_time"],
            "check_in_photo_url": r["check_in_photo_url"],
            "check_out_photo_url": r["check_out_photo_url"],
            "check_in_latitude": r["check_in_latitude"],
            "check_in_longitude": r["check_in_longitude"],
            "is_within_geofence": bool(r["is_within_geofence"]),
            "attendance_status": r["attendance_status"],
            "approval_status": r["approval_status"],
            "admin_comment": r["admin_comment"]
        }
        for r in rows
    ]

    return {"success": True, "count": len(logs), "logs": logs}

@router.get("/calendar")
async def get_monthly_calendar(
    month: Optional[str] = Query(default=None, description="YYYY-MM (e.g. 2026-08)"),
    user_id_query: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 6.3: Monthly Interactive Calendar:
    Renders a full monthly grid visualization mapping daily attendance status
    (PRESENT, ABSENT, HALF_DAY, LEAVE) with distinct color codes alongside approved leave dates.
    """
    target_user_id = current_user["user_id"]
    if current_user["role"] == "HR_ADMIN" and user_id_query:
        target_user_id = user_id_query

    now = datetime.datetime.now()
    month_prefix = month or now.strftime("%Y-%m")

    cursor = db.cursor()

    # 1. Fetch attendance records for this month
    cursor.execute("""
        SELECT attendance_id, attendance_date, check_in_time, check_out_time,
               attendance_status, approval_status, is_within_geofence
        FROM attendance
        WHERE user_id = %s AND attendance_date LIKE %s
        ORDER BY attendance_date ASC
    """, (target_user_id, f"{month_prefix}%"))
    att_rows = cursor.fetchall()

    att_map = {}
    for r in att_rows:
        att_map[r["attendance_date"]] = {
            "attendance_id": r["attendance_id"],
            "attendance_status": r["attendance_status"],
            "approval_status": r["approval_status"],
            "check_in_time": r["check_in_time"],
            "check_out_time": r["check_out_time"],
            "is_within_geofence": bool(r["is_within_geofence"])
        }

    # 2. Fetch approved leaves overlapping this month
    cursor.execute("""
        SELECT leave_id, leave_type, start_date, end_date, leave_status
        FROM leave_requests
        WHERE user_id = %s AND leave_status = 'APPROVED'
          AND (start_date LIKE %s OR end_date LIKE %s)
    """, (target_user_id, f"{month_prefix}%", f"{month_prefix}%"))
    leave_rows = cursor.fetchall()

    leave_dates = {}
    for l in leave_rows:
        try:
            st = datetime.date.fromisoformat(l["start_date"])
            en = datetime.date.fromisoformat(l["end_date"])
            curr = st
            while curr <= en:
                if curr.strftime("%Y-%m") == month_prefix:
                    leave_dates[curr.strftime("%Y-%m-%d")] = {
                        "leave_id": l["leave_id"],
                        "leave_type": l["leave_type"],
                        "leave_status": l["leave_status"]
                    }
                curr += datetime.timedelta(days=1)
        except ValueError:
            pass

    return {
        "success": True,
        "month": month_prefix,
        "user_id": target_user_id,
        "attendance_by_date": att_map,
        "approved_leaves_by_date": leave_dates
    }

@router.get("/admin/flagged")
async def get_admin_flagged_attendance(
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 6.2: Dedicated HR Admin Queue for Flagged Location / Photo Attendance.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT a.attendance_id, a.user_id, u.employee_id, u.first_name, u.last_name, u.email, u.department,
               a.attendance_date, a.check_in_time, a.check_in_photo_url,
               a.check_in_latitude, a.check_in_longitude, a.is_within_geofence,
               a.attendance_status, a.approval_status, a.admin_comment
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        WHERE a.approval_status IN ('PENDING_ADMIN_APPROVAL', 'REJECTED')
        ORDER BY a.attendance_id DESC
    """)
    rows = cursor.fetchall()

    flagged = [
        {
            "attendance_id": r["attendance_id"],
            "user_id": r["user_id"],
            "employee_id": r["employee_id"],
            "employee_name": f"{r['first_name']} {r['last_name']}",
            "email": r["email"],
            "department": r["department"],
            "attendance_date": r["attendance_date"],
            "check_in_time": r["check_in_time"],
            "check_in_photo_url": r["check_in_photo_url"],
            "check_in_latitude": r["check_in_latitude"],
            "check_in_longitude": r["check_in_longitude"],
            "is_within_geofence": bool(r["is_within_geofence"]),
            "attendance_status": r["attendance_status"],
            "approval_status": r["approval_status"],
            "admin_comment": r["admin_comment"],
            "maps_url": f"https://www.google.com/maps%sq={r['check_in_latitude']},{r['check_in_longitude']}"
        }
        for r in rows
    ]

    return {"success": True, "count": len(flagged), "flagged_logs": flagged}

@router.patch("/admin/verify/{attendance_id}")
async def admin_verify_attendance(
    attendance_id: int,
    payload: AdminVerifyAttendanceSchema,
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 6.2: Admin review endpoint to set approval_status to APPROVED or REJECTED.
    """
    cursor = db.cursor()
    cursor.execute("SELECT attendance_id, user_id, approval_status FROM attendance WHERE attendance_id = %s", (attendance_id,))
    rec = cursor.fetchone()

    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Attendance record not found."}
        )

    comment = payload.admin_comment or f"Decision {payload.approval_status} by HR Director ({admin_user.get('email')})"

    cursor.execute("""
        UPDATE attendance 
        SET approval_status = %s, admin_comment = %s, verified_by = %s
        WHERE attendance_id = %s
    """, (payload.approval_status, comment, admin_user["user_id"], attendance_id))
    db.commit()

    return {
        "success": True,
        "message": f"Attendance #{attendance_id} updated to {payload.approval_status}.",
        "data": {
            "attendance_id": attendance_id,
            "approval_status": payload.approval_status,
            "admin_comment": comment
        }
    }
