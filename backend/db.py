import psycopg2
import psycopg2.extras
import os
import bcrypt

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is not set!")
    conn = psycopg2.connect(DATABASE_URL)
    # Using RealDictCursor so rows behave like dicts (similar to sqlite3.Row)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    if not DATABASE_URL:
        print("Skipping init_db, no DATABASE_URL")
        return
        
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    cursor = conn.cursor()

    # Note: PostgreSQL uses SERIAL instead of AUTOINCREMENT, and DATETIME is TIMESTAMP
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            employee_id VARCHAR(50) UNIQUE NOT NULL,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL CHECK(role IN ('HR_ADMIN', 'EMPLOYEE')),
            is_verified INTEGER NOT NULL DEFAULT 0,
            phone VARCHAR(20),
            address TEXT,
            profile_picture_url TEXT,
            job_title VARCHAR(100),
            department VARCHAR(100),
            joining_date DATE,
            leave_balance_paid INTEGER DEFAULT 18,
            leave_balance_sick INTEGER DEFAULT 10,
            documents_url TEXT DEFAULT 'https://mybuddyhrms.com/docs/employee_records.pdf',
            salary_base DECIMAL(10, 2) DEFAULT 5000.00,
            salary_allowances DECIMAL(10, 2) DEFAULT 500.00,
            salary_deductions DECIMAL(10, 2) DEFAULT 250.00,
            net_salary DECIMAL(10, 2) DEFAULT 5250.00,
            is_email_verified INTEGER NOT NULL DEFAULT 0,
            verification_token TEXT,
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMP DEFAULT NULL,
            last_activity TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS leave_requests (
            leave_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            leave_type VARCHAR(20) NOT NULL CHECK(leave_type IN ('PAID', 'SICK', 'UNPAID')),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            leave_reason TEXT NOT NULL,
            leave_status VARCHAR(20) NOT NULL CHECK(leave_status IN ('PENDING', 'APPROVED', 'REJECTED')) DEFAULT 'PENDING',
            admin_comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attendance (
            attendance_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            attendance_date DATE NOT NULL,
            check_in_time VARCHAR(20),
            check_out_time VARCHAR(20),
            check_in_photo_url TEXT,
            check_out_photo_url TEXT,
            check_in_latitude REAL NOT NULL,
            check_in_longitude REAL NOT NULL,
            is_within_geofence INTEGER NOT NULL,
            attendance_status VARCHAR(20) NOT NULL CHECK(attendance_status IN ('PRESENT', 'ABSENT', 'HALF_DAY', 'LEAVE')),
            approval_status VARCHAR(25) NOT NULL CHECK(approval_status IN ('AUTO_APPROVED', 'PENDING_ADMIN_APPROVAL', 'APPROVED', 'REJECTED')),
            admin_comment TEXT,
            verified_by INTEGER REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS payroll (
            payroll_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            salary_base DECIMAL(10, 2) NOT NULL,
            salary_allowances DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
            salary_deductions DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
            net_salary DECIMAL(10, 2) NOT NULL,
            monthly_wage DECIMAL(10, 2) DEFAULT 5000.00,
            basic_salary DECIMAL(10, 2) DEFAULT 2500.00,
            hra DECIMAL(10, 2) DEFAULT 1250.00,
            standard_allowance DECIMAL(10, 2) DEFAULT 250.00,
            performance_bonus DECIMAL(10, 2) DEFAULT 250.00,
            lta DECIMAL(10, 2) DEFAULT 250.00,
            fixed_allowance DECIMAL(10, 2) DEFAULT 500.00,
            pf_employee DECIMAL(10, 2) DEFAULT 300.00,
            pf_employer DECIMAL(10, 2) DEFAULT 300.00,
            professional_tax DECIMAL(10, 2) DEFAULT 200.00,
            salary_config TEXT DEFAULT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Seed Admin User if none exists
    cursor.execute("SELECT id FROM users WHERE email = %s", ('admin@mybuddyhrms.com',))
    if not cursor.fetchone():
        admin_pass_hash = bcrypt.hashpw(b"Admin@12345", bcrypt.gensalt()).decode('utf-8')
        emp_pass_hash = bcrypt.hashpw(b"Employee@12345", bcrypt.gensalt()).decode('utf-8')

        cursor.execute("""
            INSERT INTO users (employee_id, first_name, last_name, email, password_hash, role, phone, address, profile_picture_url, job_title, department, joining_date, documents_url, salary_base, salary_allowances, salary_deductions, net_salary, is_email_verified, leave_balance_paid, leave_balance_sick)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 24, 12)
        """, (
            'EMP-001', 'Sarah', 'Jenkins', 'admin@mybuddyhrms.com', admin_pass_hash, 'HR_ADMIN',
            '+1 (555) 234-5678', '124 Corporate HQ, Bangalore', 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150',
            'HR Director', 'Human Resources', '2025-01-10', 'https://mybuddyhrms.com/docs/sarah_records.pdf',
            8500.00, 850.00, 425.00, 8925.00
        ))

        cursor.execute("""
            INSERT INTO users (employee_id, first_name, last_name, email, password_hash, role, phone, address, profile_picture_url, job_title, department, joining_date, documents_url, salary_base, salary_allowances, salary_deductions, net_salary, is_email_verified, leave_balance_paid, leave_balance_sick)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 18, 10)
        """, (
            'EMP-002', 'John', 'Doe', 'john.doe@mybuddyhrms.com', emp_pass_hash, 'EMPLOYEE',
            '+1 (555) 876-5432', '45 Greenfield Ave, Bangalore', 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150',
            'Senior Fullstack Engineer', 'Engineering', '2025-06-15', 'https://mybuddyhrms.com/docs/john_records.pdf',
            6200.00, 620.00, 310.00, 6510.00
        ))
        conn.commit()

        cursor.execute("SELECT id FROM users WHERE email = 'john.doe@mybuddyhrms.com'")
        emp_id = cursor.fetchone()["id"]

        cursor.execute("""
            INSERT INTO attendance (user_id, attendance_date, check_in_time, check_out_time, check_in_photo_url, check_in_latitude, check_in_longitude, is_within_geofence, attendance_status, approval_status, admin_comment)
            VALUES (%s, CURRENT_DATE - INTERVAL '1 day', '09:15:00', '17:45:00', 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150', 12.9716, 77.5946, 1, 'PRESENT', 'AUTO_APPROVED', 'In office geofence')
        """, (emp_id,))
        
        cursor.execute("""
            INSERT INTO attendance (user_id, attendance_date, check_in_time, check_out_time, check_in_photo_url, check_in_latitude, check_in_longitude, is_within_geofence, attendance_status, approval_status, admin_comment)
            VALUES (%s, CURRENT_DATE - INTERVAL '2 days', '09:05:00', '18:10:00', 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150', 12.9716, 77.5946, 1, 'PRESENT', 'AUTO_APPROVED', 'In office geofence')
        """, (emp_id,))
        
        cursor.execute("""
            INSERT INTO leave_requests (user_id, leave_type, start_date, end_date, leave_reason, leave_status)
            VALUES (%s, 'SICK', CURRENT_DATE - INTERVAL '5 days', CURRENT_DATE - INTERVAL '4 days', 'Fever and cold', 'APPROVED')
        """, (emp_id,))

        conn.commit()

    conn.close()

init_db()
