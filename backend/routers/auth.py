import datetime
import psycopg2
import psycopg2.extras
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, EmailStr

from backend.db import get_db
from backend.security import hash_password, verify_password, validate_password_strength, create_access_token
from backend.middleware import get_current_user, MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES
from backend.schemas import UserSignUpSchema, UserLoginSchema, VerifyEmailSchema

router = APIRouter(prefix="", tags=["Authentication Engine (Prompt 2)"])

@router.post("/signup", status_code=status.HTTP_201_CREATED)
@router.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignUpSchema, db: psycopg2.extensions.connection = Depends(get_db)):
    """
    Prompt 2: Registration Endpoint taking employee_id, first_name, last_name, email, password, and role.
    Triggers automated verification token generation and sets is_email_verified = false.
    """
    # 1. Password security strength validation
    is_strong, msg, _ = validate_password_strength(payload.password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": msg}
        )

    cursor = db.cursor()

    # 2. Duplicate email check
    cursor.execute("SELECT id FROM users WHERE email = %s COLLATE NOCASE", (payload.email,))
    if cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"success": False, "message": f"An employee account with email '{payload.email}' already exists."}
        )

    # 3. Duplicate employee_id check
    cursor.execute("SELECT id FROM users WHERE employee_id = %s", (payload.employee_id,))
    if cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"success": False, "message": f"Employee ID '{payload.employee_id}' is already registered."}
        )

    # 4. Create user record with is_email_verified = false
    pwd_hash = hash_password(payload.password)
    verification_token = secrets.token_urlsafe(32)

    cursor.execute("""
        INSERT INTO users (
            employee_id, first_name, last_name, email, password_hash, role,
            is_email_verified, verification_token,
            salary_base, salary_allowances, salary_deductions, net_salary,
            created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, 0, %s, 5000.00, 500.00, 250.00, 5250.00, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id
    """, (
        payload.employee_id.strip(),
        payload.first_name.strip(),
        payload.last_name.strip(),
        payload.email.strip().lower(),
        pwd_hash,
        payload.role,
        verification_token
    ))
    db.commit()
    user_id = cursor.fetchone()["id"]

    # Create matching initial payroll entry
    cursor.execute("""
        INSERT INTO payroll (user_id, salary_base, salary_allowances, salary_deductions, net_salary)
        VALUES (%s, 5000.00, 500.00, 250.00, 5250.00)
    """, (user_id,))
    db.commit()

    return {
        "success": True,
        "message": "Account registered successfully. Automated verification link generated.",
        "data": {
            "user_id": user_id,
            "employee_id": payload.employee_id,
            "email": payload.email,
            "role": payload.role,
            "is_email_verified": False,
            "verification_token": verification_token,
            "verification_url": f"/verify-email?token={verification_token}"
        }
    }

@router.get("/verify-email")
@router.post("/verify-email")
@router.post("/api/auth/verify-email")
@router.post("/api/v1/auth/verify-email")
async def verify_email(
    token: str = Query(default=None),
    payload: VerifyEmailSchema = None,
    db: psycopg2.extensions.connection = Depends(get_db)
):
    """
    Prompt 2: Verification API (/verify-email?token=...) updating is_email_verified = true.
    """
    actual_token = token or (payload.token if payload else None)
    if not actual_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Verification token is required."}
        )

    cursor = db.cursor()
    cursor.execute("SELECT id, email, is_email_verified FROM users WHERE verification_token = %s", (actual_token,))
    user = cursor.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Invalid or expired verification token."}
        )

    cursor.execute("""
        UPDATE users 
        SET is_email_verified = 1, verification_token = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (user["id"],))
    db.commit()

    return {
        "success": True,
        "message": f"Email '{user['email']}' verified successfully! You may now sign in.",
        "is_email_verified": True
    }

@router.post("/login")
@router.post("/api/auth/login")
@router.post("/api/v1/auth/login")
async def login(payload: UserLoginSchema, request: Request, db: psycopg2.extensions.connection = Depends(get_db)):
    """
    Prompt 2: Login endpoint taking email and password.
    Verifies credentials and email confirmation status (is_email_verified),
    enforces 3-trials lockout policy, and returns JWT containing user_id and role.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, password_hash, role,
               is_email_verified, verification_token, failed_login_attempts, locked_until
        FROM users WHERE email = %s COLLATE NOCASE
    """, (payload.email.strip().lower(),))
    user = cursor.fetchone()

    now = datetime.datetime.now(datetime.timezone.utc)

    # User existence check
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Invalid email or password credentials."}
        )

    # 1. Check account lockout status
    if user["locked_until"]:
        try:
            locked_time = datetime.datetime.fromisoformat(user["locked_until"])
            if locked_time > now:
                mins_left = max(1, int((locked_time - now).total_seconds() / 60))
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail={
                        "success": False,
                        "message": f"Account is temporarily locked due to 3 consecutive failed login attempts. Try again in {mins_left} minute(s) or contact HR Admin.",
                        "is_locked": True,
                        "locked_until": user["locked_until"]
                    }
                )
        except ValueError:
            pass

    # 2. Verify password credentials
    if not verify_password(payload.password, user["password_hash"]):
        new_attempts = user["failed_login_attempts"] + 1
        trials_left = max(0, MAX_LOGIN_ATTEMPTS - new_attempts)

        if new_attempts >= MAX_LOGIN_ATTEMPTS:
            locked_until = (now + datetime.timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            cursor.execute("""
                UPDATE users 
                SET failed_login_attempts = %s, locked_until = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (new_attempts, locked_until, user["id"]))
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={
                    "success": False,
                    "message": f"Account locked for {LOCKOUT_MINUTES} minutes due to 3 consecutive incorrect password attempts.",
                    "is_locked": True,
                    "locked_until": locked_until
                }
            )
        else:
            cursor.execute("UPDATE users SET failed_login_attempts = %s WHERE id = %s", (new_attempts, user["id"]))
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "success": False,
                    "message": f"Invalid email or password credentials. {trials_left} trial(s) remaining before account lockout.",
                    "trials_remaining": trials_left
                }
            )

    # 3. Check email verification status
    if not user["is_email_verified"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "message": "Email address is unverified. Please verify your email before logging in.",
                "is_email_verified": False,
                "verification_token": user["verification_token"]
            }
        )

    # 4. Reset failed attempts & update last activity
    cursor.execute("""
        UPDATE users 
        SET failed_login_attempts = 0, locked_until = NULL, last_activity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (now.isoformat(), user["id"]))
    db.commit()

    # 5. Issue session JWT containing user_id and role
    token_payload = {
        "user_id": user["id"],
        "employee_id": user["employee_id"],
        "email": user["email"],
        "role": user["role"]
    }
    jwt_token = create_access_token(token_payload)

    return {
        "success": True,
        "message": "Authentication successful.",
        "token": jwt_token,
        "user": {
            "user_id": user["id"],
            "id": user["id"],
            "employee_id": user["employee_id"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "email": user["email"],
            "role": user["role"],
            "is_email_verified": bool(user["is_email_verified"])
        }
    }

@router.get("/api/auth/me")
@router.get("/api/v1/auth/me")
@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), db: psycopg2.extensions.connection = Depends(get_db)):
    """
    Returns currently authenticated user identity context.
    """
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, employee_id, first_name, last_name, email, role, phone, address, profile_picture_url,
               job_title, department, joining_date, documents_url, salary_base, net_salary, is_email_verified
        FROM users WHERE id = %s
    """, (current_user["user_id"],))
    u = cursor.fetchone()

    if not u:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "success": True,
        "user": {
            "user_id": u["id"],
            "id": u["id"],
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
            "net_salary": float(u["net_salary"] or 0),
            "is_email_verified": bool(u["is_email_verified"])
        }
    }
