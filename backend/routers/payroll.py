import json
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.db import get_db
from backend.middleware import get_current_user, require_role
from backend.schemas import AdminAdjustPayrollSchema
from backend.utils.salary_calculator import compute_salary_breakdown

router = APIRouter(
    prefix="/api/v1/payroll",
    tags=["Payroll & Compensation Management (Prompt 8 & Granular Salary Engine)"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/my-payslips")
async def get_my_payroll_breakdown(
    current_user: dict = Depends(get_current_user),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 8.1: Employee Payroll View:
    Provide a read-only salary breakdown displaying granular computed fields
    (monthly_wage, basic_salary, hra, allowances, deductions, and net_salary).
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT p.payroll_id, p.user_id, p.salary_base, p.salary_allowances, p.salary_deductions,
               p.net_salary, p.monthly_wage, p.basic_salary, p.hra, p.standard_allowance,
               p.performance_bonus, p.lta, p.fixed_allowance, p.pf_employee, p.pf_employer,
               p.professional_tax, p.salary_config, p.updated_at,
               u.employee_id, u.first_name, u.last_name, u.department, u.job_title
        FROM payroll p
        JOIN users u ON p.user_id = u.id
        WHERE p.user_id = %s
        ORDER BY p.payroll_id DESC
    """, (current_user["user_id"],))
    rows = cursor.fetchall()

    records = []
    for r in rows:
        wage = float(r["monthly_wage"] or r["salary_base"] or 5000.0)
        basic = float(r["basic_salary"] or round(wage * 0.5, 2))
        hra = float(r["hra"] or round(basic * 0.5, 2))
        std_allow = float(r["standard_allowance"] or round(wage * 0.05, 2))
        perf = float(r["performance_bonus"] or round(wage * 0.05, 2))
        lta = float(r["lta"] or round(wage * 0.05, 2))
        fixed = float(r["fixed_allowance"] or round(wage - (basic + hra + std_allow + perf + lta), 2))
        pf_emp = float(r["pf_employee"] or round(basic * 0.12, 2))
        pf_empr = float(r["pf_employer"] or round(basic * 0.12, 2))
        pt = float(r["professional_tax"] or 200.0)

        records.append({
            "payroll_id": r["payroll_id"],
            "user_id": r["user_id"],
            "employee_id": r["employee_id"],
            "employee_name": f"{r['first_name']} {r['last_name']}",
            "job_title": r["job_title"],
            "department": r["department"],
            "monthly_wage": wage,
            "basic_salary": basic,
            "hra": hra,
            "standard_allowance": std_allow,
            "performance_bonus": perf,
            "lta": lta,
            "fixed_allowance": fixed,
            "pf_employee": pf_emp,
            "pf_employer": pf_empr,
            "professional_tax": pt,
            "salary_base": float(r["salary_base"] or wage),
            "salary_allowances": float(r["salary_allowances"]),
            "salary_deductions": float(r["salary_deductions"]),
            "net_salary": float(r["net_salary"]),
            "salary_config": json.loads(r["salary_config"]) if r["salary_config"] else None,
            "updated_at": r["updated_at"]
        })

    return {"success": True, "count": len(records), "payroll_records": records}

@router.get("/admin/overview")
async def get_admin_payroll_overview(
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 8.2: Admin Payroll Control Workspace:
    List all employees with real-time computed granular salary components and net_salary.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.id as user_id, u.employee_id, u.first_name, u.last_name, u.department, u.job_title,
               u.salary_base, u.salary_allowances, u.salary_deductions, u.net_salary,
               u.monthly_wage, u.basic_salary, u.hra, u.standard_allowance, u.performance_bonus,
               u.lta, u.fixed_allowance, u.pf_employee, u.pf_employer, u.professional_tax,
               (SELECT COUNT(*) FROM attendance a WHERE a.user_id = u.id AND a.attendance_status = 'PRESENT') as present_days,
               (SELECT COUNT(*) FROM leave_requests l WHERE l.user_id = u.id AND l.leave_status = 'APPROVED' AND l.leave_type = 'UNPAID') as unpaid_leave_days
        FROM users u
        ORDER BY u.id ASC
    """)
    users = cursor.fetchall()

    payroll_sheet = []
    total_cost = 0.0

    for u in users:
        wage = float(u["monthly_wage"] or u["salary_base"] or 5000.0)
        net = float(u["net_salary"] or 0)
        total_cost += net

        payroll_sheet.append({
            "user_id": u["user_id"],
            "employee_id": u["employee_id"],
            "employee_name": f"{u['first_name']} {u['last_name']}",
            "department": u["department"],
            "job_title": u["job_title"],
            "monthly_wage": wage,
            "basic_salary": float(u["basic_salary"] or round(wage * 0.5, 2)),
            "hra": float(u["hra"] or round(wage * 0.25, 2)),
            "standard_allowance": float(u["standard_allowance"] or round(wage * 0.05, 2)),
            "performance_bonus": float(u["performance_bonus"] or round(wage * 0.05, 2)),
            "lta": float(u["lta"] or round(wage * 0.05, 2)),
            "fixed_allowance": float(u["fixed_allowance"] or 0),
            "pf_employee": float(u["pf_employee"] or round(wage * 0.5 * 0.12, 2)),
            "pf_employer": float(u["pf_employer"] or round(wage * 0.5 * 0.12, 2)),
            "professional_tax": float(u["professional_tax"] or 200.0),
            "salary_base": float(u["salary_base"] or wage),
            "salary_allowances": float(u["salary_allowances"] or 0),
            "salary_deductions": float(u["salary_deductions"] or 0),
            "net_salary": net,
            "present_days": u["present_days"],
            "unpaid_leave_days": u["unpaid_leave_days"]
        })

    return {
        "success": True,
        "total_staff": len(payroll_sheet),
        "total_payroll_cost": total_cost,
        "payroll_sheet": payroll_sheet
    }

@router.put("/admin/adjust/{target_user_id}")
async def adjust_employee_payroll(
    target_user_id: int,
    payload: AdminAdjustPayrollSchema,
    admin_user: dict = Depends(require_role("HR_ADMIN")),
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Phase 2: Backend Calculation Engine (FastAPI)
    Auto-computes the entire structure when an Admin submits a new 'Monthly Wage' (or base configuration).

    Step 1: Calculate Basic: Wage * 50%
    Step 2: Calculate HRA: Basic * 50%
    Step 3: Calculate percentage-based allowances (Standard, Performance, LTA).
    Step 4: Calculate Fixed Allowance: Wage - (Basic + HRA + Standard + Performance + LTA)
    Step 5: Calculate Deductions: PF (Basic * 12%) and PT (Fixed 200).
    Step 6: Calculate Net Salary: Wage - (PF + PT).
    """
    cursor = db.cursor()
    cursor.execute("SELECT id, email, salary_base FROM users WHERE id = %s", (target_user_id,))
    target = cursor.fetchone()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Target employee record not found."}
        )

    # Determine wage input
    wage_input = payload.monthly_wage if payload.monthly_wage is not None else payload.salary_base
    if wage_input is None:
        wage_input = float(target["salary_base"] or 5000.0)

    # Check if explicit allowances/deductions were passed without monthly_wage
    if payload.monthly_wage is None and payload.salary_allowances is not None and payload.salary_deductions is not None:
        base = float(payload.salary_base or 5000.0)
        allowances = float(payload.salary_allowances)
        deductions = float(payload.salary_deductions)
        net_salary = round(base + allowances - deductions, 2)

        # Still calculate breakdown fields for consistency
        calc = compute_salary_breakdown(
            monthly_wage=base,
            basic_pct=payload.basic_pct or 0.50,
            hra_pct=payload.hra_pct or 0.50,
            standard_allowance_pct=payload.standard_allowance_pct or 0.05,
            performance_bonus_pct=payload.performance_bonus_pct or 0.05,
            lta_pct=payload.lta_pct or 0.05,
            pf_pct=payload.pf_pct or 0.12,
            professional_tax=payload.professional_tax or 200.00
        )
        calc["salary_base"] = base
        calc["salary_allowances"] = allowances
        calc["salary_deductions"] = deductions
        calc["net_salary"] = net_salary
    else:
        # Run standard 6-step calculation engine
        calc = compute_salary_breakdown(
            monthly_wage=wage_input,
            basic_pct=payload.basic_pct or 0.50,
            hra_pct=payload.hra_pct or 0.50,
            standard_allowance_pct=payload.standard_allowance_pct or 0.05,
            performance_bonus_pct=payload.performance_bonus_pct or 0.05,
            lta_pct=payload.lta_pct or 0.05,
            pf_pct=payload.pf_pct or 0.12,
            professional_tax=payload.professional_tax or 200.00
        )

    # Update users table
    cursor.execute("""
        UPDATE users 
        SET monthly_wage = %s, basic_salary = %s, hra = %s, standard_allowance = %s,
            performance_bonus = %s, lta = %s, fixed_allowance = %s, pf_employee = %s,
            pf_employer = %s, professional_tax = %s, salary_config = %s,
            salary_base = %s, salary_allowances = %s, salary_deductions = %s, net_salary = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (
        calc["monthly_wage"], calc["basic_salary"], calc["hra"], calc["standard_allowance"],
        calc["performance_bonus"], calc["lta"], calc["fixed_allowance"], calc["pf_employee"],
        calc["pf_employer"], calc["professional_tax"], calc["salary_config"],
        calc["salary_base"], calc["salary_allowances"], calc["salary_deductions"], calc["net_salary"],
        target_user_id
    ))

    # Update or insert payroll table
    cursor.execute("SELECT payroll_id FROM payroll WHERE user_id = %s", (target_user_id,))
    existing = cursor.fetchone()

    if existing:
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

    db.commit()

    return {
        "success": True,
        "message": f"Salary breakdown computed for employee {target['email']}. Net salary: ${calc['net_salary']:.2f}.",
        "data": {
            "user_id": target_user_id,
            "monthly_wage": calc["monthly_wage"],
            "basic_salary": calc["basic_salary"],
            "hra": calc["hra"],
            "standard_allowance": calc["standard_allowance"],
            "performance_bonus": calc["performance_bonus"],
            "lta": calc["lta"],
            "fixed_allowance": calc["fixed_allowance"],
            "pf_employee": calc["pf_employee"],
            "pf_employer": calc["pf_employer"],
            "professional_tax": calc["professional_tax"],
            "salary_base": calc["salary_base"],
            "salary_allowances": calc["salary_allowances"],
            "salary_deductions": calc["salary_deductions"],
            "net_salary": calc["net_salary"]
        }
    }
