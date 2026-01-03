# routes/admin_dashboard.py
"""
Admin Dashboard API for Team Management
CLEANED VERSION: Removed duplicates and redundant endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional
from datetime import datetime, date as date_type, timedelta, timezone
from sqlmodel import Session, select, func, and_, or_

from core.database import get_session
from core.security import get_current_admin
from models.models import User, Organization, UserRole
from models.attendance_models import Attendance
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


# ============================================================
# 📊 DATA SCHEMAS (Response Models)
# ============================================================

class EmployeeBasicInfo(BaseModel):
    """Employee basic information"""
    id: int
    full_name: str
    email: str
    role: str
    job_title: Optional[str] = None
    department: Optional[str] = None
    profile_picture: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class AttendanceRecordForAdmin(BaseModel):
    """Attendance record with employee info for admin view"""
    id: int
    user_id: int
    date: date_type
    check_in: Optional[str] = None  # Time as string (HH:MM:SS)
    check_out: Optional[str] = None
    total_hours: Optional[str] = None
    productive_hours: Optional[str] = None
    break_time: Optional[str] = None
    overtime: Optional[str] = None
    status: str
    location: Optional[str] = None
    is_late: bool
    notes: Optional[str] = None
    
    # Geolocation data
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    
    # Employee details
    employee: EmployeeBasicInfo
    
    class Config:
        from_attributes = True


class WeeklyAttendanceSummary(BaseModel):
    """Weekly summary for an employee"""
    user_id: int
    employee_name: str
    week_start: date_type
    week_end: date_type
    total_days: int
    present_days: int
    absent_days: int
    late_days: int
    total_hours: str
    average_hours_per_day: str
    attendance_percentage: float

    class Config:
        from_attributes = True


class TeamAttendanceStats(BaseModel):
    """Overall team attendance statistics"""
    total_employees: int
    checked_in_today: int
    checked_out_today: int
    absent_today: int
    late_today: int
    average_hours_today: str
    attendance_rate_today: float
    
    class Config:
        from_attributes = True


class AdminDashboardData(BaseModel):
    """Complete dashboard data"""
    stats: TeamAttendanceStats
    attendance_records: List[AttendanceRecordForAdmin]
    weekly_summaries: List[WeeklyAttendanceSummary]

    class Config:
        from_attributes = True


# ============================================================
# ✅ HELPER FUNCTIONS (Tenant-aware)
# ============================================================

def _get_org_id_from_admin(current_user: User) -> int:
    """
    Extract organization ID from admin user.
    Ensures tenant isolation.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin not associated with an organization"
        )
    return current_user.organization_id


def _format_datetime_iso(date_obj, time_obj) -> Optional[str]:
    """Combine date and time to ISO format (UTC)"""
    if not time_obj or not date_obj:
        return None
    
    if isinstance(time_obj, str):
        # Already a string, try to append date if it looks like just time
        return time_obj
        
    # Combine date and time
    dt = datetime.combine(date_obj, time_obj)
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        
    return dt.isoformat()


def _calculate_hours_string(total_minutes: Optional[int]) -> str:
    """Convert minutes to HH:MM format"""
    if total_minutes is None or total_minutes <= 0:
        return "00:00"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


# ============================================================
# 🎯 ESSENTIAL ADMIN ENDPOINTS (Only what's actually needed)
# ============================================================

@router.get("/team/members", response_model=List[EmployeeBasicInfo])
async def get_team_members(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    is_active: Optional[bool] = Query(True, description="Filter by active status"),
    role: Optional[str] = Query(None, description="Filter by role")
):
    """
    Get list of team members in the organization.
    """
    org_id = _get_org_id_from_admin(current_user)
    
    conditions = [User.organization_id == org_id]
    
    if is_active is not None:
        conditions.append(User.is_active == is_active)
    
    if role:
        conditions.append(User.role == role)
    
    members = session.exec(
        select(User).where(and_(*conditions)).order_by(User.full_name)
    ).all()
    
    return [EmployeeBasicInfo.from_orm(m) for m in members]


@router.get("/attendance/today", response_model=List[AttendanceRecordForAdmin])
async def get_today_attendance(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    sort_by: str = Query("employee.name", description="Sort by field"),
    show_all: bool = Query(True, description="Show all employees including those without attendance")
):
    """
    Get all attendance records for today.
    """
    org_id = _get_org_id_from_admin(current_user)
    today = date_type.today()
    
    # Get ALL active employees in organization
    all_employees = session.exec(
        select(User).where(
            and_(
                User.organization_id == org_id,
                User.is_active == True
            )
        )
    ).all()
    
    # Get attendance records for today
    attendance_records = session.exec(
        select(Attendance).where(
            and_(
                Attendance.organization_id == org_id,
                Attendance.date == today
            )
        )
    ).all()
    
    # Create a map of user_id -> attendance record for quick lookup
    attendance_map = {record.user_id: record for record in attendance_records}
    
    response = []
    
    for employee in all_employees:
        record = attendance_map.get(employee.id)
        
        if record:
            # Employee has attendance record for today
            response.append(
                AttendanceRecordForAdmin(
                    id=record.id,
                    user_id=record.user_id,
                    date=record.date,
                    check_in=_format_datetime_iso(record.date, record.check_in),
                    check_out=_format_datetime_iso(record.date, record.check_out),
                    total_hours=record.total_hours,
                    productive_hours=record.productive_hours,
                    break_time=record.break_time,
                    overtime=record.overtime,
                    status=record.status,
                    location=record.location,
                    is_late=record.is_late,
                    notes=record.notes,
                    latitude=record.latitude,
                    longitude=record.longitude,
                    address=record.address,
                    employee=EmployeeBasicInfo.from_orm(employee)
                )
            )
        elif show_all:
            # Employee has NO attendance record for today (absent)
            response.append(
                AttendanceRecordForAdmin(
                    id=0,
                    user_id=employee.id,
                    date=today,
                    check_in=None,
                    check_out=None,
                    total_hours=None,
                    productive_hours=None,
                    break_time=None,
                    overtime=None,
                    status="absent",
                    location=None,
                    is_late=False,
                    notes=None,
                    latitude=None,
                    longitude=None,
                    address=None,
                    employee=EmployeeBasicInfo.from_orm(employee)
                )
            )
    
    # Apply sorting
    if sort_by == "employee.name":
        response.sort(key=lambda x: x.employee.full_name)
    elif sort_by == "check_in":
        # Sort by check_in time (nulls last)
        response.sort(key=lambda x: (x.check_in is None, x.check_in))
    elif sort_by == "status":
        response.sort(key=lambda x: x.status)
    
    return response


@router.get("/attendance/", response_model=List[AttendanceRecordForAdmin])
async def get_attendance_records(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    start_date: Optional[date_type] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date_type] = Query(None, description="End date (YYYY-MM-DD)"),
    user_id: Optional[int] = Query(None, description="Filter by employee ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    location: Optional[str] = Query(None, description="Filter by location"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """
    Get attendance records with filters.
    """
    org_id = _get_org_id_from_admin(current_user)
    
    # Build conditions
    conditions = [Attendance.organization_id == org_id]
    
    if start_date:
        conditions.append(Attendance.date >= start_date)
    
    if end_date:
        conditions.append(Attendance.date <= end_date)
    
    if user_id:
        # Verify user belongs to organization
        user = session.exec(
            select(User).where(
                and_(
                    User.id == user_id,
                    User.organization_id == org_id
                )
            )
        ).first()
        if user:
            conditions.append(Attendance.user_id == user_id)
    
    if status:
        conditions.append(Attendance.status == status)
    
    if location:
        conditions.append(Attendance.location == location)
    
    # Query with join
    query = (
        select(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .where(and_(*conditions))
        .order_by(Attendance.date.desc(), User.full_name)
    )
    
    # Apply pagination
    total_count = session.exec(select(func.count(Attendance.id)).where(and_(*conditions))).one()
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    results = session.exec(query).all()
    
    # Transform to response
    response = []
    for attendance, user in results:
        response.append(
            AttendanceRecordForAdmin(
                id=attendance.id,
                user_id=attendance.user_id,
                date=attendance.date,
                check_in=_format_datetime_iso(attendance.date, attendance.check_in),
                check_out=_format_datetime_iso(attendance.date, attendance.check_out),
                total_hours=attendance.total_hours,
                productive_hours=attendance.productive_hours,
                break_time=attendance.break_time,
                overtime=attendance.overtime,
                status=attendance.status,
                location=attendance.location,
                is_late=attendance.is_late,
                notes=attendance.notes,
                latitude=attendance.latitude,
                longitude=attendance.longitude,
                address=attendance.address,
                employee=EmployeeBasicInfo.from_orm(user)
            )
        )
    
    return response


@router.get("/attendance/summary")
async def get_attendance_summary(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100)
):
    """
    Get attendance summary for all users in the organization.
    """
    org_id = _get_org_id_from_admin(current_user)
    
    # Use current month/year if not specified
    if month is None:
        month = datetime.now(timezone.utc).month
    if year is None:
        year = datetime.now(timezone.utc).year
    
    # Get all employees in organization
    employees = session.exec(
        select(User).where(
            and_(
                User.organization_id == org_id,
                User.is_active == True
            )
        )
    ).all()
    
    # Get attendance records for the month
    records = session.exec(
        select(Attendance).where(
            and_(
                Attendance.organization_id == org_id,
                Attendance.month == month,
                Attendance.year == year
            )
        )
    ).all()
    
    # Group records by user
    records_by_user = {}
    for record in records:
        if record.user_id not in records_by_user:
            records_by_user[record.user_id] = []
        records_by_user[record.user_id].append(record)
    
    # Create summary for each employee
    summary = []
    for employee in employees:
        user_records = records_by_user.get(employee.id, [])
        
        present_days = len({r.date for r in user_records if r.status == "present"})
        absent_days = len({r.date for r in user_records if r.status == "absent"})
        leave_days = len({r.date for r in user_records if r.status == "leave"})
        late_days = len({r.date for r in user_records if r.is_late})
        
        total_minutes = sum(r.total_minutes or 0 for r in user_records)
        total_hours_str = _calculate_hours_string(total_minutes)
        
        avg_minutes = total_minutes // len(user_records) if user_records else 0
        avg_hours_str = _calculate_hours_string(avg_minutes)
        
        summary.append({
            "employee_id": employee.id,
            "employee_name": employee.full_name,
            "email": employee.email,
            "role": employee.role,
            "total_days": len(user_records),
            "present_days": present_days,
            "absent_days": absent_days,
            "leave_days": leave_days,
            "late_days": late_days,
            "total_hours": total_hours_str,
            "average_hours": avg_hours_str,
            "attendance_percentage": round((present_days / max(len(user_records), 1)) * 100, 2)
        })
    
    return {
        "month": month,
        "year": year,
        "summary": summary,
        "total_employees": len(employees),
        "total_records": len(records)
    }


@router.get("/dashboard/full", response_model=AdminDashboardData)
async def get_full_dashboard(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    date: Optional[date_type] = Query(None, description="Date for records (defaults to today)")
):
    """
    Get complete dashboard data in one request.
    """
    org_id = _get_org_id_from_admin(current_user)
    target_date = date or date_type.today()
    
    # 1. Get ALL active employees in organization
    all_employees = session.exec(
        select(User).where(
            and_(
                User.organization_id == org_id,
                User.is_active == True
            )
        )
    ).all()
    
    # 2. Get stats
    total_employees = len(all_employees)
    today_records = session.exec(
        select(Attendance).where(
            and_(
                Attendance.organization_id == org_id,
                Attendance.date == target_date
            )
        )
    ).all()
    
    present_employees = {record.user_id for record in today_records if record.status == "present"}
    checked_in_count = sum(1 for r in today_records if r.check_in is not None)
    checked_out_count = sum(1 for r in today_records if r.check_out is not None)
    absent_count = total_employees - len(present_employees)
    late_count = sum(1 for r in today_records if r.is_late)
    
    total_minutes = sum(r.total_minutes or 0 for r in today_records)
    avg_hours_str = _calculate_hours_string(
        total_minutes // len(present_employees) if present_employees else 0
    )
    attendance_rate = (len(present_employees) / total_employees * 100) if total_employees > 0 else 0
    
    stats = TeamAttendanceStats(
        total_employees=total_employees,
        checked_in_today=checked_in_count,
        checked_out_today=checked_out_count,
        absent_today=absent_count,
        late_today=late_count,
        average_hours_today=avg_hours_str,
        attendance_rate_today=round(attendance_rate, 2)
    )
    
    # 3. Create attendance records for today (including absent employees)
    attendance_map = {record.user_id: record for record in today_records}
    attendance_records = []
    
    for employee in all_employees:
        record = attendance_map.get(employee.id)
        
        if record:
            attendance_records.append(
                AttendanceRecordForAdmin(
                    id=record.id,
                    user_id=record.user_id,
                    date=record.date,
                    check_in=_format_datetime_iso(record.date, record.check_in),
                    check_out=_format_datetime_iso(record.date, record.check_out),
                    total_hours=record.total_hours,
                    productive_hours=record.productive_hours,
                    break_time=record.break_time,
                    overtime=record.overtime,
                    status=record.status,
                    location=record.location,
                    is_late=record.is_late,
                    notes=record.notes,
                    latitude=record.latitude,
                    longitude=record.longitude,
                    address=record.address,
                    employee=EmployeeBasicInfo.from_orm(employee)
                )
            )
        else:
            # Absent employee
            attendance_records.append(
                AttendanceRecordForAdmin(
                    id=0,
                    user_id=employee.id,
                    date=target_date,
                    check_in=None,
                    check_out=None,
                    total_hours=None,
                    productive_hours=None,
                    break_time=None,
                    overtime=None,
                    status="absent",
                    location=None,
                    is_late=False,
                    notes=None,
                    latitude=None,
                    longitude=None,
                    address=None,
                    employee=EmployeeBasicInfo.from_orm(employee)
                )
            )
    
    # 4. Get weekly summaries for all employees
    week_summaries = []
    
    # Calculate week range
    weekday = target_date.weekday()
    week_start = target_date - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)
    
    for employee in all_employees:
        weekly_records = session.exec(
            select(Attendance).where(
                and_(
                    Attendance.user_id == employee.id,
                    Attendance.organization_id == org_id,
                    Attendance.date >= week_start,
                    Attendance.date <= week_end
                )
            )
        ).all()

        # Get current week's Monday (start of week)
        today = datetime.now().date()
        current_week_monday = today - timedelta(days=today.weekday())

        # Count ALL present days from this Monday onwards (Mon-Sun)
        present_dates = {r.date for r in weekly_records 
                        if r.status == "present" 
                        and r.date >= current_week_monday}
        present_days = len(present_dates)

        # Count absences only for Mon-Fri (for tracking purposes)
        absent_dates = {r.date for r in weekly_records 
                        if r.status == "absent" 
                        and r.date.weekday() < 5}
        absent_days = len(absent_dates)

        # Calculate attendance rate (present days / unique days recorded)
        total_unique_days = len({r.date for r in weekly_records})
        attendance_rate = (present_days / total_unique_days * 100) if total_unique_days > 0 else 0

        
        late_days = len({r.date for r in weekly_records if r.is_late})
        
        total_minutes = sum(r.total_minutes or 0 for r in weekly_records)
        total_hours_str = _calculate_hours_string(total_minutes)
        
        avg_minutes = total_minutes // len(weekly_records) if weekly_records else 0
        avg_hours_str = _calculate_hours_string(avg_minutes)
        
        working_days = 5
        attendance_pct = (present_days / working_days * 100) if working_days > 0 else 0
        
        week_summaries.append(
            WeeklyAttendanceSummary(
                user_id=employee.id,
                employee_name=employee.full_name,
                week_start=week_start,
                week_end=week_end,
                total_days=len(weekly_records),
                present_days=present_days,
                absent_days=absent_days,
                late_days=late_days,
                total_hours=total_hours_str,
                average_hours_per_day=avg_hours_str,
                attendance_percentage=round(attendance_pct, 2)
            )
        )
    
    return AdminDashboardData(
        stats=stats,
        attendance_records=attendance_records,
        weekly_summaries=week_summaries
    )


# ============================================================
# 🐛 DEBUG ENDPOINTS (Keep only for troubleshooting)
# ============================================================

@router.get("/debug/check-data")
async def debug_check_data(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Debug endpoint to check organization data
    """
    org_id = _get_org_id_from_admin(current_user)
    today = date_type.today()
    
    # Get all users in organization
    all_users = session.exec(
        select(User).where(User.organization_id == org_id)
    ).all()
    
    # Get today's attendance
    today_attendance = session.exec(
        select(Attendance).where(
            and_(
                Attendance.organization_id == org_id,
                Attendance.date == today
            )
        )
    ).all()
    
    # Get all attendance records in org
    all_attendance = session.exec(
        select(Attendance).where(Attendance.organization_id == org_id)
    ).all()
    
    return {
        "current_admin": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.full_name,
            "role": current_user.role,
            "org_id": current_user.organization_id
        },
        "organization_stats": {
            "total_users": len(all_users),
            "users_by_role": {
                "admin": len([u for u in all_users if u.role in ["admin", "super_admin"]]),
                "manager": len([u for u in all_users if u.role == "manager"]),
                "employee": len([u for u in all_users if u.role == "employee"]),
                "others": len([u for u in all_users if u.role not in ["admin", "super_admin", "manager", "employee"]])
            },
            "today_attendance_count": len(today_attendance),
            "total_attendance_records": len(all_attendance)
        },
        "users_list": [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
                "has_attendance_today": any(a.user_id == u.id for a in today_attendance)
            }
            for u in all_users
        ]
    }