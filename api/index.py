import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import auth, admin, employee, attendance, leaves, payroll, profile, users

app = FastAPI(title="MY BUDDY HRMS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(employee.router)
app.include_router(attendance.router)
app.include_router(leaves.router)
app.include_router(payroll.router)
app.include_router(profile.router)
app.include_router(users.router)

@app.get("/api/health")
async def health_check():
    return {"status": "online", "service": "Vercel Serverless API"}
