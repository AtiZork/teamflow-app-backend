import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

from core.database import create_db_and_tables
from routes.auth import router as auth_router
from routes.projects import router as project_router
from routes.tasks import router as tasks_router
from routes.invitation import router as invitation_router
from routes.users import router as users_router      
from routes.profile import router as profile_router 
from routes.payment import router as payment_router
from routes.timesheet import router as timesheet_router
from routes.attendance import router as attendance_router  
from routes.hours_tracking import router as hours_router
from routes.admin_dashboard import router as admin_dashboard_router
from routes.leave_routes import router as leave_management_router
from routes.organization import router as organization_router
from routes.sales_marketing import router as sales_marketing_router
from notifications.routes import router as notifications_router

# =========================================
# 🏁 Lifespan (DB initialization)
# =========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - runs on startup and shutdown.
    
    On STARTUP:
    -----------
    1. Creates all database tables (idempotent)
    2. Seeds default leave types for all organizations (idempotent)
    
    This ensures that on every deploy (Render, Railway, Fly.io):
    - Database schema is up to date
    - All organizations have default leave types
    - No manual intervention required
    
    On SHUTDOWN:
    -----------
    - Performs cleanup operations
    """
    # ===== STARTUP =====
    print("🚀 [STARTUP] Initializing TeamFlow Backend...")
    
    # Step 1: Ensure all database tables exist
    # This is safe to run on every startup (idempotent)
    create_db_and_tables()
    print("✅ [STARTUP] Database tables created/verified.")
    
    # Step 2: Seed default leave types for all organizations
    # WHY: In production, databases start fresh on deploy
    # This ensures leave types are always available
    # Safe to run multiple times (checks existing data first)
    from services.seed_service import seed_default_leave_types
    seed_default_leave_types()
    print("✅ [STARTUP] Leave types initialization complete.")
    
    print("🎉 [STARTUP] Application ready to accept requests.")
    
    # ===== RUNNING =====
    yield
    
    # ===== SHUTDOWN =====
    print("👋 [SHUTDOWN] Application shutting down gracefully.")

# =========================================
#  ✅ FastAPI App
# =========================================
app = FastAPI(lifespan=lifespan, title="TeamFlow App Backend")

# Configure CORS. In development we allow local frontends (localhost/127.0.0.1)
# To enable permissive local CORS, set the environment variable DEV=true
dev_mode = os.getenv("DEV", "false").lower() in ("1", "true", "yes")

if dev_mode:
    # Use a regex to allow localhost and 127.0.0.1 on any port during development.
    # Note: when using regex, allow_credentials can remain True.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    allowed_origins = [
        "https://teamflow-frontend-omega.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# =========================================
# 📦 Routers
# =========================================
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(project_router, prefix="/projects", tags=["Projects"])
app.include_router(tasks_router, prefix="/tasks", tags=["Tasks"])
app.include_router(users_router, prefix="/users", tags=["Users"])       
app.include_router(invitation_router, prefix="/auth", tags=["Invitations"])
app.include_router(organization_router)
app.include_router(profile_router, tags=["Profile"]) 
app.include_router(payment_router)  # ✅ Stripe Payment Integration
app.include_router(timesheet_router)
app.include_router(attendance_router)  # ✅ Attendance management
app.include_router(hours_router)
app.include_router(admin_dashboard_router)  # ✅ Admin Dashboard API
app.include_router(leave_management_router)
app.include_router(sales_marketing_router)
app.include_router(notifications_router)


# =========================================
# 📁 Static Files (Uploads)
# =========================================
app.mount("/static", StaticFiles(directory="uploads"), name="static")

# =========================================
# 🩺 Health Check
# =========================================
@app.get("/health")
def health_check():
    """Basic health check endpoint"""
    return {"status": "ok", "message": "Backend is running"}


@app.get("/health/leave-types")
def health_check_leave_types():
    """
    Health check endpoint for Leave Types initialization.
    
    Returns the status of leave types for all organizations.
    Useful for debugging production issues and verifying automatic seeding.
    
    Returns:
        JSON with:
        - total_organizations: Number of organizations in DB
        - organizations_with_leave_types: Count of orgs with leave types
        - organizations_without_leave_types: Count of orgs without leave types
        - details: Per-organization breakdown
    """
    from sqlmodel import Session, select
    from core.database import engine
    from models.models import Organization
    from services.seed_service import get_leave_type_count_for_organization
    
    try:
        with Session(engine) as session:
            organizations = session.exec(select(Organization)).all()
            
            org_details = []
            orgs_with_types = 0
            orgs_without_types = 0
            
            for org in organizations:
                count = get_leave_type_count_for_organization(org.id)
                org_details.append({
                    "organization_id": org.id,
                    "organization_name": org.name,
                    "leave_types_count": count,
                    "status": "✅ OK" if count > 0 else "❌ Missing"
                })
                
                if count > 0:
                    orgs_with_types += 1
                else:
                    orgs_without_types += 1
            
            return {
                "status": "ok" if orgs_without_types == 0 else "warning",
                "total_organizations": len(organizations),
                "organizations_with_leave_types": orgs_with_types,
                "organizations_without_leave_types": orgs_without_types,
                "details": org_details
            }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/")
def read_root():
    return {"message": "Welcome to TeamFlow Backend!"}

