import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from backend.db import get_db
from backend.middleware import get_current_user, require_role
from backend.schemas import EmployeeSelfProfileUpdateSchema, AdminProfileUpdateSchema
from backend.utils.salary_calculator import compute_salary_breakdown

router = APIRouter(
    prefix="/api/v1/profile",
    tags=["Employee Profile Management (Prompt 5)"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/")
@router.get("")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 5.1: Profile View Component:
    Render profile_picture_url, first_name, last_name, employee_id, email, phone, address,
    job_title, department, joining_date, and documents_url alongside protected salary keys (salary_base, net_salary).
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, role, phone, address, profile_picture_url,
               job_title, department, joining_date, documents_url, salary_base, salary_allowances,
               salary_deductions, net_salary, leave_balance_paid, leave_balance_sick, is_email_verified, created_at
        FROM users WHERE id = %s
    """, (current_user["user_id"],))
    u = cursor.fetchone()

    if not u:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Profile not found."}
        )

    return {
        "success": True,
        "profile": {
            "user_id": u["id"],
            "employee_id": u["employee_id"],
            "first_name": u["first_name"],
            "last_name": u["last_name"],
            "full_name": f"{u['first_name']} {u['last_name']}",
            "email": u["email"],
            "role": u["role"],
            "phone": u["phone"] or "Not provided",
            "address": u["address"] or "Not provided",
            "profile_picture_url": u["profile_picture_url"] or "https://images.unsplash.com/photo-1534528741775-53994a69daeb%sw=150",
            "job_title": u["job_title"],
            "department": u["department"],
            "joining_date": u["joining_date"],
            "documents_url": u["documents_url"] or "https://mybuddyhrms.com/docs/employee_records.pdf",
            "salary_base": float(u["salary_base"] or 0),
            "salary_allowances": float(u["salary_allowances"] or 0),
            "salary_deductions": float(u["salary_deductions"] or 0),
            "net_salary": float(u["net_salary"] or 0),
            "leave_balance_paid": u["leave_balance_paid"],
            "leave_balance_sick": u["leave_balance_sick"],
            "is_email_verified": bool(u["is_email_verified"]),
            "created_at": u["created_at"]
        }
    }

@router.patch("/self")
async def update_self_profile(
    payload: EmployeeSelfProfileUpdateSchema,
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 5.2: Role-Based Field Security:
    For users with role = EMPLOYEE, restrict write access to phone, address, and profile_picture_url.
    """
    cursor = db.cursor()
    updates = []
    params = []

    if payload.phone is not None:
        updates.append("phone = %s")
        params.append(payload.phone.strip())
    if payload.address is not None:
        updates.append("address = %s")
        params.append(payload.address.strip())
    if payload.profile_picture_url is not None:
        updates.append("profile_picture_url = %s")
        params.append(payload.profile_picture_url.strip())

    if not updates:
        return {"success": True, "message": "No profile update values provided."}

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(current_user["user_id"])

    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
    db.commit()

    return {
        "success": True,
        "message": "Personal profile updated successfully."
    }

@router.patch("/admin/{target_user_id}")
async def admin_update_profile(
    target_user_id: int,
    payload: AdminProfileUpdateSchema,
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 5.2: Role-Based Field Security:
    For users with role = HR_ADMIN, enable comprehensive modification rights across all data fields,
    including documents_url, organizational placement, and compensation logic.
    """
    cursor = db.cursor()
    cursor.execute("SELECT id, email, salary_base, salary_allowances, salary_deductions FROM users WHERE id = %s", (target_user_id,))
    target = cursor.fetchone()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Target employee record not found."}
        )

    updates = []
    params = []

    if payload.phone is not None:
        updates.append("phone = %s")
        params.append(payload.phone.strip())
    if payload.address is not None:
        updates.append("address = %s")
        params.append(payload.address.strip())
    if payload.profile_picture_url is not None:
        updates.append("profile_picture_url = %s")
        params.append(payload.profile_picture_url.strip())
    if payload.job_title is not None:
        updates.append("job_title = %s")
        params.append(payload.job_title.strip())
    if payload.department is not None:
        updates.append("department = %s")
        params.append(payload.department.strip())
    if payload.documents_url is not None:
        updates.append("documents_url = %s")
        params.append(payload.documents_url.strip())
    if payload.leave_balance_paid is not None:
        updates.append("leave_balance_paid = %s")
        params.append(payload.leave_balance_paid)
    if payload.leave_balance_sick is not None:
        updates.append("leave_balance_sick = %s")
        params.append(payload.leave_balance_sick)

    # Compensation calculation logic using 6-step calculation engine
    wage_input = payload.monthly_wage if payload.monthly_wage is not None else payload.salary_base

    if wage_input is not None or payload.salary_allowances is not None or payload.salary_deductions is not None:
        if payload.monthly_wage is None and payload.salary_allowances is not None and payload.salary_deductions is not None:
            base = float(payload.salary_base if payload.salary_base is not None else target["salary_base"] or 5000.0)
            allow = float(payload.salary_allowances)
            ded = float(payload.salary_deductions)
            net = round(base + allow - ded, 2)
            calc = compute_salary_breakdown(base)
            calc["salary_base"] = base
            calc["salary_allowances"] = allow
            calc["salary_deductions"] = ded
            calc["net_salary"] = net
        else:
            calc = compute_salary_breakdown(
                monthly_wage=wage_input if wage_input is not None else float(target["salary_base"] or 5000.0),
                basic_pct=payload.basic_pct or 0.50,
                hra_pct=payload.hra_pct or 0.50,
                standard_allowance_pct=payload.standard_allowance_pct or 0.05,
                performance_bonus_pct=payload.performance_bonus_pct or 0.05,
                lta_pct=payload.lta_pct or 0.05,
                pf_pct=payload.pf_pct or 0.12,
                professional_tax=payload.professional_tax or 200.00
            )

        updates.extend([
            "monthly_wage = %s", "basic_salary = %s", "hra = %s", "standard_allowance = %s",
            "performance_bonus = %s", "lta = %s", "fixed_allowance = %s", "pf_employee = %s",
            "pf_employer = %s", "professional_tax = %s", "salary_config = %s",
            "salary_base = %s", "salary_allowances = %s", "salary_deductions = %s", "net_salary = %s"
        ])
        params.extend([
            calc["monthly_wage"], calc["basic_salary"], calc["hra"], calc["standard_allowance"],
            calc["performance_bonus"], calc["lta"], calc["fixed_allowance"], calc["pf_employee"],
            calc["pf_employer"], calc["professional_tax"], calc["salary_config"],
            calc["salary_base"], calc["salary_allowances"], calc["salary_deductions"], calc["net_salary"]
        ])

        # Update matching payroll table record
        cursor.execute("SELECT payroll_id FROM payroll WHERE user_id = %s", (target_user_id,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE payroll 
                SET monthly_wage = %s, basic_salary = %s, hra = %s, standard_allowance = %s,
                    performance_bonus = %s, lta = %s, fixed_allowance = %s, pf_employee = %s,
                    pf_employer = %s, professional_tax = %s, salary_config = %s,
                    salary_base = %s, salary_allowances = %s, salary_deductions = %s, net_salary = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (
                calc["monthly_wage"], calc["basic_salary"], calc["hra"], calc["standard_allowance"],
                calc["performance_bonus"], calc["lta"], calc["fixed_allowance"], calc["pf_employee"],
                calc["pf_employer"], calc["professional_tax"], calc["salary_config"],
                calc["salary_base"], calc["salary_allowances"], calc["salary_deductions"], calc["net_salary"],
                target_user_id
            ))
        else:
            cursor.execute("""
                INSERT INTO payroll (
                    user_id, monthly_wage, basic_salary, hra, standard_allowance,
                    performance_bonus, lta, fixed_allowance, pf_employee, pf_employer,
                    professional_tax, salary_config, salary_base, salary_allowances,
                    salary_deductions, net_salary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                target_user_id,
                calc["monthly_wage"], calc["basic_salary"], calc["hra"], calc["standard_allowance"],
                calc["performance_bonus"], calc["lta"], calc["fixed_allowance"], calc["pf_employee"],
                calc["pf_employer"], calc["professional_tax"], calc["salary_config"],
                calc["salary_base"], calc["salary_allowances"], calc["salary_deductions"], calc["net_salary"]
            ))

    if not updates:
        return {"success": True, "message": "No administrative updates provided."}

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(target_user_id)

    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
    db.commit()

    # Re-fetch for response
    cursor.execute("SELECT salary_base, net_salary FROM users WHERE id = %s", (target_user_id,))
    final_u = cursor.fetchone()

    return {
        "success": True,
        "message": f"Administrative updates applied to employee {target['email']}.",
        "data": {
            "user_id": target_user_id,
            "salary_base": float(final_u["salary_base"]),
            "net_salary": float(final_u["net_salary"])
        }
    }
