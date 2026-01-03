# routes/attendance.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
import csv
import io
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import or_, and_
from sqlmodel import Session, select, desc, func

from core.database import get_session
from core.security import get_current_user, get_current_admin, get_current_super_admin
from models.models import User
from models.models import Organization
from models.attendance_models import Attendance, ActiveSession, BreakHistory
from schemas.attendance_schema import (
    AttendanceRead, AttendanceCreate, AttendanceUpdate, 
    AttendanceStats, AttendanceSummary, AttendanceFilter,
    CheckInRequest, CheckOutRequest, BreakRequest, TodayStatus,
    AttendanceStatus, BreakType, WorkLocation
)
from notifications.service import notify_organization_admins
from notifications.models import NotificationType

router = APIRouter(prefix="/attendance", tags=["attendance"])


# Helper functions for time calculations
def parse_time_to_minutes(time_str: str) -> int:
    """Convert HH:MM string to total minutes"""
    if not time_str or time_str == "00:00":
        return 0
    try:
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes
    except:
        return 0


def format_minutes_to_time(total_minutes: int) -> str:
    """Convert total minutes to HH:MM format"""
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def format_time_display(time_obj) -> str:
    """Format time object to HH:MM AM/PM"""
    if not time_obj:
        return "--:--"
    if isinstance(time_obj, str):
        # Try to parse string time
        try:
            dt = datetime.strptime(time_obj, "%H:%M")
            return dt.strftime("%I:%M %p")
        except:
            return time_obj
    # It's a time object
    dt = datetime.combine(date.today(), time_obj)
    return dt.strftime("%I:%M %p")


# ============================================================
# ✅ CHECK IN/OUT ENDPOINTS (For all users)
# ============================================================
@router.post("/check-in", response_model=AttendanceRead)
async def check_in(
    check_in_data: CheckInRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Check in for the day.
    Enforces: One active session per user per day.
    """
    # Multi-tenant validation
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    
    # Check if already checked in today and hasn't checked out yet
    today = date.today()
    existing = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    # Strict validation: Only ONE active session allowed per day
    # User can check in ONLY if:
    # 1. No record exists for today, OR
    # 2. Previous record has both check_in AND check_out (session complete)
    if existing and existing.check_in and not existing.check_out:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already checked in today. Please check out first."
        )
    
    # Create new attendance record for this check-in
    # Always create a fresh record for new check-in cycle
    attendance = Attendance(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        date=today,
        status=AttendanceStatus.PRESENT.value
    )
    
    # Set check-in time (current server time in UTC)
    now = datetime.now(timezone.utc)
    attendance.check_in = now.time()
    attendance.location = check_in_data.location
    attendance.notes = check_in_data.notes
    attendance.latitude = check_in_data.latitude
    attendance.longitude = check_in_data.longitude
    attendance.address = check_in_data.address
    
    # Check if late (after 9:15 AM)
    if attendance.check_in > datetime.strptime("09:15", "%H:%M").time():
        attendance.is_late = True
    
    # Add to session FIRST to get the ID
    session.add(attendance)
    session.flush()  # Flush to get ID without committing
    
    # Calculate hours with db_session for accurate break calculation
    attendance.calculate_hours(db_session=session)
    
    # Create or update active session (single source of truth for "checked in" status)
    active_session = session.exec(
        select(ActiveSession)
        .where(ActiveSession.user_id == current_user.id)
    ).first()
    
    if not active_session:
        # Create new active session
        active_session = ActiveSession(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            is_checked_in=True,
            check_in_time=now,
            check_in_location=check_in_data.location,
            latitude=check_in_data.latitude,
            longitude=check_in_data.longitude,
            address=check_in_data.address
        )
        session.add(active_session)
    else:
        # Update existing session
        active_session.is_checked_in = True
        active_session.check_in_time = now
        active_session.check_in_location = check_in_data.location
        active_session.latitude = check_in_data.latitude
        active_session.longitude = check_in_data.longitude
        active_session.address = check_in_data.address
        active_session.check_out_time = None  # Reset checkout time
        session.add(active_session)
    
    # ✅ NOTIFICATION HOOK
    notify_organization_admins(
        session=session,
        organization_id=current_user.organization_id,
        sender_id=current_user.id,
        type=NotificationType.CHECK_IN,
        title="Member Checked In",
        message=f"{current_user.full_name} checked in at {attendance.check_in.strftime('%I:%M %p')}",
        entity_type="attendance",
        entity_id=attendance.id
    )

    # Commit all changes
    session.commit()
    session.refresh(attendance)
    session.refresh(active_session)
    
    return attendance


@router.post("/check-out", response_model=AttendanceRead)
async def check_out(
    check_out_data: CheckOutRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Check out for the day.
    Validates active session and calculates final work hours.
    """
    # Multi-tenant validation
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    
    # Get today's attendance
    today = date.today()
    attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    # Get active session to verify check-in status
    active_session = session.exec(
        select(ActiveSession)
        .where(ActiveSession.user_id == current_user.id)
    ).first()
    
    # Strict validation: User MUST be currently checked in
    is_currently_checked_in = False
    if active_session and active_session.is_checked_in:
        is_currently_checked_in = True
    elif attendance and attendance.check_in and not attendance.check_out:
        is_currently_checked_in = True
    
    if not is_currently_checked_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not checked in. Cannot check out."
        )
    
    # If no attendance record exists for today, create one from active session
    if not attendance:
        attendance = Attendance(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            date=today,
            status=AttendanceStatus.PRESENT.value
        )
        # Copy check-in data from active session if available
        if active_session and active_session.check_in_time:
            attendance.check_in = active_session.check_in_time.time()
            attendance.location = active_session.check_in_location
            attendance.latitude = active_session.latitude
            attendance.longitude = active_session.longitude
            attendance.address = active_session.address
        session.add(attendance)
        session.flush()  # Get ID
    
    # Set check-out time (current server time in UTC)
    now = datetime.now(timezone.utc)
    attendance.check_out = now.time()
    if check_out_data.notes:
        attendance.notes = check_out_data.notes
    
    # Calculate final hours with db_session for accurate break calculation
    # This will calculate: total_work_minutes = (checkout - checkin) - total_break_minutes
    attendance.calculate_hours(db_session=session)
    
    # Set status to indicate session is complete
    attendance.status = AttendanceStatus.PRESENT.value
    
    # Update active session - mark as checked out
    if active_session:
        active_session.is_checked_in = False
        active_session.check_out_time = now
        session.add(active_session)
    
    session.add(attendance)
    # ✅ NOTIFICATION HOOK
    notify_organization_admins(
        session=session,
        organization_id=current_user.organization_id,
        sender_id=current_user.id,
        type=NotificationType.CHECK_OUT,
        title="Member Checked Out",
        message=f"{current_user.full_name} checked out at {attendance.check_out.strftime('%I:%M %p')}",
        entity_type="attendance",
        entity_id=attendance.id
    )

    session.commit()
    session.refresh(attendance)
    
    return attendance


@router.get("/today-status", response_model=TodayStatus)
async def get_today_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get today's attendance status for current user"""
    today = date.today()
    
    # Get today's attendance
    attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    # Get active session
    active_session = session.exec(
        select(ActiveSession)
        .where(ActiveSession.user_id == current_user.id)
    ).first()
    
    # Calculate break time for TODAY'S SESSIONS (all completed breaks today)
    total_break_minutes = 0
    
    # Always get all today's breaks - this works for both checked-in and checked-out users
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    breaks = session.exec(
        select(BreakHistory)
        .where(
            BreakHistory.user_id == current_user.id,
            BreakHistory.organization_id == current_user.organization_id,
            BreakHistory.start_time >= today_start,
            BreakHistory.start_time <= today_end
        )
    ).all()
    
    # Calculate total break time from all completed breaks today
    for break_item in breaks:
        if break_item.duration:
            if ':' in break_item.duration:
                hours, minutes = break_item.duration.split(':')
                total_break_minutes += int(hours) * 60 + int(minutes)
    
    # Ensure break minutes are never negative
    total_break_minutes = max(0, total_break_minutes)
    
    break_hours = total_break_minutes // 60
    break_minutes = total_break_minutes % 60
    break_time = f"{break_hours:02d}:{break_minutes:02d}"
    
    # Calculate productive hours and total hours
    productive_hours = "00:00"
    total_hours_for_display = "00:00"
    
    # If currently checked in, calculate live from check-in time to now
    if active_session and active_session.is_checked_in and active_session.check_in_time:
        now = datetime.now(timezone.utc)
        check_in_time = active_session.check_in_time
        
        # Ensure check_in_time is aware
        if check_in_time and check_in_time.tzinfo is None:
            check_in_time = check_in_time.replace(tzinfo=timezone.utc)
        
        # Calculate total minutes from check-in to now
        time_diff = now - check_in_time
        total_minutes = int(time_diff.total_seconds() / 60)
        
        # Ensure we don't show negative hours
        if total_minutes < 0:
            total_minutes = 0
        
        # Calculate productive minutes (total - breaks)
        productive_minutes = max(0, total_minutes - total_break_minutes)
        
        # Format total hours
        total_h = total_minutes // 60
        total_m = total_minutes % 60
        total_hours_for_display = f"{total_h:02d}:{total_m:02d}"
        
        # Format productive hours
        prod_h = productive_minutes // 60
        prod_m = productive_minutes % 60
        productive_hours = f"{prod_h:02d}:{prod_m:02d}"
    elif attendance and attendance.check_in and attendance.check_out:
        # Already checked out - use stored total_hours from Attendance model
        # This is CURRENT SESSION only, NOT all day total
        total_hours_for_display = attendance.total_hours or "00:00"
        
        # Parse total hours
        if attendance.total_hours and ':' in attendance.total_hours:
            total_h, total_m = map(int, attendance.total_hours.split(':'))
            total_minutes = total_h * 60 + total_m
        else:
            total_minutes = 0
        
        # Productive hours = total - breaks from THIS session only
        productive_minutes = max(0, total_minutes - total_break_minutes)
        prod_h = productive_minutes // 60
        prod_m = productive_minutes % 60
        productive_hours = f"{prod_h:02d}:{prod_m:02d}"
    elif attendance and attendance.check_in and not attendance.check_out:
        # Partially checked in but no record in ActiveSession (edge case)
        # Calculate from check-in time to now
        now = datetime.now(timezone.utc)
        check_in_dt = datetime.combine(today, attendance.check_in)
        if check_in_dt.tzinfo is None:
            check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
            
        time_diff = now - check_in_dt
        total_minutes = max(0, int(time_diff.total_seconds() / 60))
        
        productive_minutes = max(0, total_minutes - total_break_minutes)
        
        # Format total hours
        total_h = total_minutes // 60
        total_m = total_minutes % 60
        total_hours_for_display = f"{total_h:02d}:{total_m:02d}"
        
        # Format productive hours
        prod_h = productive_minutes // 60
        prod_m = productive_minutes % 60
        productive_hours = f"{prod_h:02d}:{prod_m:02d}"
    
    # Get active break info
    active_break = None
    current_break_data = None
    if active_session and active_session.is_on_break:
        # Ensure break_start_time has UTC timezone before converting to ISO
        break_start_aware = active_session.break_start_time
        if break_start_aware and break_start_aware.tzinfo is None:
            break_start_aware = break_start_aware.replace(tzinfo=timezone.utc)
        
        active_break = {
            "break_type": active_session.break_type,
            "id": active_session.id,
            "start_time": break_start_aware.isoformat().replace('+00:00', 'Z') if break_start_aware else None,
            "notes": active_session.break_notes
        }
        current_break_data = {
            "id": active_session.id,
            "break_type": active_session.break_type,
            "start_time": break_start_aware
        }

    # Use ActiveSession as PRIMARY source of truth for check-in status
    is_checked_in = False
    check_in_time_str = None
    check_out_time_str = None
    current_location = None
    latitude = None
    longitude = None
    address = None
    
    # DEBUG: Log what we have
    print(f"DEBUG TODAY_STATUS: active_session exists: {active_session is not None}")
    if active_session:
        print(f"DEBUG TODAY_STATUS: active_session.is_checked_in: {active_session.is_checked_in}")
        print(f"DEBUG TODAY_STATUS: active_session.check_in_time: {active_session.check_in_time}")
    print(f"DEBUG TODAY_STATUS: attendance exists: {attendance is not None}")
    
    # Priority 1: Use ActiveSession for current status and location
    if active_session and active_session.is_checked_in:
        is_checked_in = True
        # Use ActiveSession data for location (persisted from check-in)
        current_location = active_session.check_in_location
        latitude = active_session.latitude
        longitude = active_session.longitude
        address = active_session.address
        # Use check_in_time from ActiveSession if available
        if active_session.check_in_time:
            # Ensure timezone is UTC before converting to ISO format
            # This fixes the issue where frontend shows wrong time (UTC instead of local)
            check_in_aware = active_session.check_in_time
            if check_in_aware.tzinfo is None:
                check_in_aware = check_in_aware.replace(tzinfo=timezone.utc)
            # Use isoformat() and explicitly format as UTC (replace +00:00 with Z if needed)
            check_in_time_str = check_in_aware.isoformat().replace('+00:00', 'Z')
    
    # Priority 2: If ActiveSession not checked in, check Attendance as fallback
    # (This handles edge cases where ActiveSession might be out of sync)
    if not is_checked_in and attendance and attendance.check_in and not attendance.check_out:
        is_checked_in = True
        
        # Create aware datetime for ISO format
        check_in_dt = datetime.combine(attendance.date, attendance.check_in)
        if check_in_dt.tzinfo is None:
            check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
        check_in_time_str = check_in_dt.isoformat()
        
        current_location = attendance.location
        latitude = attendance.latitude
        longitude = attendance.longitude
        address = attendance.address
    
    # If not checked in but we have check_in_time from attendance, use it for display
    if not is_checked_in and not check_in_time_str and attendance and attendance.check_in:
        # Create aware datetime for ISO format
        check_in_dt = datetime.combine(attendance.date, attendance.check_in)
        if check_in_dt.tzinfo is None:
            check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
        check_in_time_str = check_in_dt.isoformat()
    
    # IMPORTANT: Only show check_out_time if CURRENTLY checked out
    # When checked in, never show check_out_time (prevents confusing negative calculations)
    if not is_checked_in and attendance and attendance.check_out:
        # Create aware datetime for ISO format
        check_out_dt = datetime.combine(attendance.date, attendance.check_out)
        if check_out_dt.tzinfo is None:
            check_out_dt = check_out_dt.replace(tzinfo=timezone.utc)
        check_out_time_str = check_out_dt.isoformat()
    
    print(f"DEBUG TODAY_STATUS RESULT: is_checked_in={is_checked_in}, check_in_time={check_in_time_str}, check_out_time={check_out_time_str}")
    
    return TodayStatus(
        is_checked_in=is_checked_in,
        check_in_time=check_in_time_str,
        check_out_time=check_out_time_str,
        total_hours=total_hours_for_display,
        break_time=break_time,
        productive_hours=productive_hours,
        current_location=current_location,
        latitude=latitude,
        longitude=longitude,
        address=address,
        active_break=active_break,
        current_break=current_break_data,
        today_breaks=[{
            "id": b.id,
            "break_type": b.break_type,
            "start_time": (b.start_time.replace(tzinfo=timezone.utc) if b.start_time.tzinfo is None else b.start_time).isoformat().replace('+00:00', 'Z') if b.start_time else None,
            "end_time": (b.end_time.replace(tzinfo=timezone.utc) if b.end_time and b.end_time.tzinfo is None else b.end_time).isoformat().replace('+00:00', 'Z') if b.end_time else None,
            "duration": b.duration
        } for b in breaks]
    )


# ============================================================
# ✅ BREAK MANAGEMENT
# ============================================================
@router.post("/start-break")
async def start_break(
    break_data: BreakRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Start a break.
    Validates: User must be checked in and not already on break.
    """
    # Multi-tenant validation
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    
    # Get active session (PRIMARY source of truth for check-in status)
    active_session = session.exec(
        select(ActiveSession)
        .where(ActiveSession.user_id == current_user.id)
    ).first()
    
    # Get today's attendance
    today = date.today()
    attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    # Strict validation: User MUST be checked in
    is_checked_in = False
    if active_session and active_session.is_checked_in:
        is_checked_in = True
    elif attendance and attendance.check_in and not attendance.check_out:
        is_checked_in = True
    
    if not is_checked_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must be checked in to take a break"
        )
    
    # Prevent overlapping breaks
    if active_session and active_session.is_on_break:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already on a break. Please end current break first."
        )
    
    # Create or update active session for break tracking
    now = datetime.now(timezone.utc)
    if not active_session:
        # Edge case: User is checked in via Attendance but no ActiveSession
        # Create ActiveSession from Attendance data
        active_session = ActiveSession(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            is_checked_in=True,
            check_in_time=datetime.combine(today, attendance.check_in).replace(tzinfo=timezone.utc) if attendance and attendance.check_in else now
        )
        session.add(active_session)
        session.flush()
    
    # Mark as on break
    active_session.is_on_break = True
    active_session.break_start_time = now
    active_session.break_type = break_data.break_type
    active_session.break_notes = break_data.notes
    
    # Ensure attendance record exists
    if not attendance:
        attendance = Attendance(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            date=today,
            status=AttendanceStatus.PRESENT.value
        )
        if active_session and active_session.check_in_time:
            attendance.check_in = active_session.check_in_time.time()
            attendance.location = active_session.check_in_location
        session.add(attendance)
        session.flush()  # Get attendance.id
    
    # Create break history record (server-side timestamp)
    break_history = BreakHistory(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        attendance_id=attendance.id,
        break_type=break_data.break_type,
        start_time=now,  # Server timestamp in UTC
        notes=break_data.notes
    )
    
    session.add(active_session)
    session.add(break_history)
    # ✅ NOTIFICATION HOOK
    notify_organization_admins(
        session=session,
        organization_id=current_user.organization_id,
        sender_id=current_user.id,
        type=NotificationType.BREAK_START,
        title="Break Started",
        message=f"{current_user.full_name} started a {break_data.break_type} break",
        entity_type="attendance",
        entity_id=attendance.id
    )

    session.commit()
    
    return {"message": f"Break started: {break_data.break_type}", "break_id": break_history.id}


@router.post("/end-break")
async def end_break(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    End current break.
    Calculates duration and updates attendance hours.
    """
    # Multi-tenant validation
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    
    # Get active session
    active_session = session.exec(
        select(ActiveSession)
        .where(ActiveSession.user_id == current_user.id)
    ).first()
    
    # Validate: Must have an active break
    if not active_session or not active_session.is_on_break:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active break to end"
        )
    
    # Get today's attendance
    today = date.today()
    attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    # Find the latest break history record without end time
    break_query = select(BreakHistory).where(
        BreakHistory.user_id == current_user.id,
        BreakHistory.organization_id == current_user.organization_id,
        BreakHistory.end_time.is_(None)
    ).order_by(desc(BreakHistory.start_time))
    
    break_history = session.exec(break_query).first()
    
    # Current server time (UTC)
    now = datetime.now(timezone.utc)
    
    # Update break history with end time and calculate duration
    if break_history:
        break_history.end_time = now
        
        # Ensure start_time is timezone-aware
        if break_history.start_time.tzinfo is None:
            break_history.start_time = break_history.start_time.replace(tzinfo=timezone.utc)
            
        # Calculate duration (server-side)
        duration = now - break_history.start_time
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        break_history.duration = f"{hours:02d}:{minutes:02d}"
        session.add(break_history)
    
    # Update active session - clear break state
    active_session.is_on_break = False
    active_session.break_start_time = None
    active_session.break_type = None
    active_session.break_notes = None
    session.add(active_session)
    
    # Recalculate attendance hours with updated break data
    if attendance:
        # Pass db_session to get real-time break data from BreakHistory
        attendance.calculate_hours(db_session=session)
        session.add(attendance)
    else:
        # Edge case: Create attendance record if it doesn't exist
        attendance = Attendance(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            date=today,
            status=AttendanceStatus.PRESENT.value
        )
        if active_session and active_session.check_in_time:
            attendance.check_in = active_session.check_in_time.time()
            attendance.location = active_session.check_in_location
        attendance.calculate_hours(db_session=session)
        session.add(attendance)
    session.flush() # Ensure ID is populated
    
    # ✅ NOTIFICATION HOOK (if attendance record exists)
    if attendance:
        notify_organization_admins(
            session=session,
            organization_id=current_user.organization_id,
            sender_id=current_user.id,
            type=NotificationType.BREAK_END,
            title="Break Ended",
            message=f"{current_user.full_name} ended break ({break_history.duration if break_history else 'unknown'})",
            entity_type="attendance",
            entity_id=attendance.id
        )

    # Commit all changes
    session.commit()
    
    return {
        "message": "Break ended successfully",
        "break_duration": break_history.duration if break_history else "00:00"
    }
# ============================================================
@router.get("/stats", response_model=AttendanceStats)
async def get_attendance_stats(
    date_filter: date = Query(None, description="Get stats for specific date (default: today)"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Get attendance statistics for organization (Admin only)"""
    target_date = date_filter or date.today()
    
    # Get all users in organization
    total_users = session.exec(
        select(User)
        .where(
            User.organization_id == current_user.organization_id,
            User.is_active == True
        )
    ).all()
    
    # Get attendance for target date
    attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.organization_id == current_user.organization_id,
            Attendance.date == target_date
        )
    ).all()
    
    # ✅ FIX: Count actively checked-in users from ActiveSession table
    # This gives real-time count of members who are currently checked in
    if target_date == date.today():
        # For today, count active check-ins from ActiveSession table
        active_sessions = session.exec(
            select(ActiveSession)
            .where(
                ActiveSession.organization_id == current_user.organization_id,
                ActiveSession.is_checked_in == True
            )
        ).all()
        present_today = len(active_sessions)
    else:
        # For historical dates, count attendance records with check_in time
        present_today = len([a for a in attendances if a.check_in is not None])
    
    on_leave = len([a for a in attendances if a.status == AttendanceStatus.LEAVE.value])
    late_arrivals = len([a for a in attendances if a.is_late])
    
    # Calculate average hours (last 30 days)
    thirty_days_ago = target_date - timedelta(days=30)
    recent_attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= thirty_days_ago,
            Attendance.date <= target_date,
            Attendance.total_hours.is_not(None)
        )
    ).all()
    
    total_hours = 0
    count = 0
    for att in recent_attendances:
        if att.total_hours:
            try:
                hours, minutes = map(int, att.total_hours.split(':'))
                total_hours += hours + (minutes / 60)
                count += 1
            except:
                pass
    
    average_hours = round(total_hours / count, 1) if count > 0 else 0
    
    # Location stats - for today use ActiveSession, for historical dates use Attendance
    if target_date == date.today():
        remote_workers = len([s for s in active_sessions if s.check_in_location == WorkLocation.REMOTE.value])
        office_workers = len([s for s in active_sessions if s.check_in_location == WorkLocation.OFFICE.value])
    else:
        remote_workers = len([a for a in attendances if a.location == WorkLocation.REMOTE.value])
        office_workers = len([a for a in attendances if a.location == WorkLocation.OFFICE.value])
    
    return AttendanceStats(
        total_employees=len(total_users),
        present_today=present_today,
        on_leave=on_leave,
        average_hours=average_hours,
        late_arrivals=late_arrivals,
        remote_workers=remote_workers,
        office_workers=office_workers
    )


@router.get("/", response_model=List[AttendanceRead])
async def get_attendance_records(
    start_date: Optional[date] = Query(None, description="Start date for filter"),
    end_date: Optional[date] = Query(None, description="End date for filter"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    location: Optional[str] = Query(None, description="Filter by location"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Get attendance records with filters (Admin only)"""
    query = select(Attendance).where(
        Attendance.organization_id == current_user.organization_id
    )
    
    # Apply filters
    if start_date:
        query = query.where(Attendance.date >= start_date)
    if end_date:
        query = query.where(Attendance.date <= end_date)
    if user_id:
        query = query.where(Attendance.user_id == user_id)
    if status:
        query = query.where(Attendance.status == status)
    if location:
        query = query.where(Attendance.location == location)
    
    # Order by date (newest first)
    query = query.order_by(desc(Attendance.date), desc(Attendance.check_in))
    
    records = session.exec(query).all()
    
    # Add employee info
    result = []
    for record in records:
        user = session.get(User, record.user_id)
        record_dict = record.dict()
        if user:
            record_dict["employee_name"] = user.full_name
            record_dict["employee_role"] = user.job_title or user.role
            record_dict["employee_avatar"] = user.profile_picture or user.full_name[:2].upper()
        result.append(record_dict)
    
    return result


@router.get("/summary", response_model=List[AttendanceSummary])
async def get_attendance_summary(
    month: Optional[int] = Query(None, description="Month (1-12)"),
    year: Optional[int] = Query(None, description="Year"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Get attendance summary for all users (Admin only)"""
    # Default to current month
    now = datetime.now(timezone.utc)
    target_month = month or now.month
    target_year = year or now.year
    
    # Get all active users in organization
    users = session.exec(
        select(User)
        .where(
            User.organization_id == current_user.organization_id,
            User.is_active == True
        )
    ).all()
    
    result = []
    for user in users:
        # Calculate date range for the month
        if target_month == 12:
            next_month = 1
            next_year = target_year + 1
        else:
            next_month = target_month + 1
            next_year = target_year
        
        start_date = date(target_year, target_month, 1)
        end_date = date(next_year, next_month, 1) - timedelta(days=1)
        
        # Get user's attendance for the month
        attendances = session.exec(
            select(Attendance)
            .where(
                Attendance.user_id == user.id,
                Attendance.organization_id == current_user.organization_id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
        ).all()
        
        # Calculate stats
        total_days = (end_date - start_date).days + 1
        present_days = len([a for a in attendances if a.status == AttendanceStatus.PRESENT.value])
        absent_days = len([a for a in attendances if a.status == AttendanceStatus.ABSENT.value])
        leave_days = len([a for a in attendances if a.status == AttendanceStatus.LEAVE.value])
        late_count = len([a for a in attendances if a.is_late])
        
        # Calculate average hours
        total_hours = 0
        hours_count = 0
        for att in attendances:
            if att.total_hours:
                try:
                    hours, minutes = map(int, att.total_hours.split(':'))
                    total_hours += hours + (minutes / 60)
                    hours_count += 1
                except:
                    pass
        
        average_hours = round(total_hours / hours_count, 1) if hours_count > 0 else 0
        
        # Get last check-in
        last_attendance = session.exec(
            select(Attendance)
            .where(Attendance.user_id == user.id)
            .order_by(desc(Attendance.date))
        ).first()
        
        last_check_in = None
        if last_attendance and last_attendance.check_in:
            last_check_in = datetime.combine(last_attendance.date, last_attendance.check_in)
        
        result.append(AttendanceSummary(
            user_id=user.id,
            employee_name=user.full_name,
            employee_role=user.job_title or user.role,
            total_days=total_days,
            present_days=present_days,
            absent_days=absent_days,
            leave_days=leave_days,
            average_hours=average_hours,
            late_count=late_count,
            last_check_in=last_check_in
        ))
    
    return result


@router.post("/manual", response_model=AttendanceRead)
async def create_manual_attendance(
    attendance_data: AttendanceCreate,
    user_id: int = Query(..., description="User ID to create attendance for"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Create manual attendance record (Admin only)"""
    # Verify user belongs to same organization
    user = session.get(User, user_id)
    if not user or user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in your organization"
        )
    
    # Check if attendance already exists for the date
    existing = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == user_id,
            Attendance.date == attendance_data.date,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attendance already exists for {attendance_data.date}"
        )
    
    # Create attendance record
    attendance = Attendance(
        user_id=user_id,
        organization_id=current_user.organization_id,
        date=attendance_data.date,
        check_in=attendance_data.check_in,
        check_out=attendance_data.check_out,
        location=attendance_data.location.value if attendance_data.location else None,
        status=attendance_data.status.value,
        notes=attendance_data.notes
    )
    
    # Set breaks
    if attendance_data.breaks:
        breaks_list = []
        for break_item in attendance_data.breaks:
            breaks_list.append({
                "type": break_item.type.value,
                "start": break_item.start_time.strftime("%H:%M") if break_item.start_time else None,
                "end": break_item.end_time.strftime("%H:%M") if break_item.end_time else None,
                "duration": break_item.duration or "00:00"
            })
        attendance.breaks_list = breaks_list
    
    # Calculate hours and check if late
    attendance.calculate_hours()
    attendance.check_if_late()
    
    session.add(attendance)
    session.commit()
    session.refresh(attendance)
    
    # Add employee info
    attendance_dict = attendance.dict()
    attendance_dict["employee_name"] = user.full_name
    attendance_dict["employee_role"] = user.job_title or user.role
    attendance_dict["employee_avatar"] = user.profile_picture or user.full_name[:2].upper()
    
    return attendance_dict


@router.put("/{attendance_id}", response_model=AttendanceRead)
async def update_attendance(
    attendance_id: int,
    attendance_data: AttendanceUpdate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Update attendance record (Admin only)"""
    attendance = session.get(Attendance, attendance_id)
    if not attendance or attendance.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found"
        )
    
    # Update fields
    if attendance_data.check_in is not None:
        attendance.check_in = attendance_data.check_in
    if attendance_data.check_out is not None:
        attendance.check_out = attendance_data.check_out
    if attendance_data.location is not None:
        attendance.location = attendance_data.location.value
    if attendance_data.status is not None:
        attendance.status = attendance_data.status.value
    if attendance_data.is_late is not None:
        attendance.is_late = attendance_data.is_late
    if attendance_data.notes is not None:
        attendance.notes = attendance_data.notes
    
    # Update breaks
    if attendance_data.breaks is not None:
        breaks_list = []
        for break_item in attendance_data.breaks:
            breaks_list.append({
                "type": break_item.type.value,
                "start": break_item.start_time.strftime("%H:%M") if break_item.start_time else None,
                "end": break_item.end_time.strftime("%H:%M") if break_item.end_time else None,
                "duration": break_item.duration or "00:00"
            })
        attendance.breaks_list = breaks_list
    
    # Recalculate
    attendance.calculate_hours()
    
    session.add(attendance)
    session.commit()
    session.refresh(attendance)
    
    # Add employee info
    user = session.get(User, attendance.user_id)
    attendance_dict = attendance.dict()
    if user:
        attendance_dict["employee_name"] = user.full_name
        attendance_dict["employee_role"] = user.job_title or user.role
        attendance_dict["employee_avatar"] = user.profile_picture or user.full_name[:2].upper()
    
    return attendance_dict


@router.delete("/{attendance_id}")
async def delete_attendance(
    attendance_id: int,
    current_user: User = Depends(get_current_super_admin),
    session: Session = Depends(get_session)
):
    """Delete attendance record (Super Admin only)"""
    attendance = session.get(Attendance, attendance_id)
    if not attendance or attendance.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found"
        )
    
    session.delete(attendance)
    session.commit()
    
    return {"message": "Attendance record deleted successfully"}


@router.get("/hours/summary")
async def get_hours_summary(
    user_id: Optional[int] = Query(None, description="User ID (optional, default: current user)"),
    period: str = Query("monthly", description="Period: daily, weekly, monthly, yearly"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get aggregated hours summary for a period"""
    target_user_id = user_id or current_user.id
    
    # Base query
    query = select(Attendance).where(
        Attendance.user_id == target_user_id,
        Attendance.organization_id == current_user.organization_id,
        Attendance.status == AttendanceStatus.PRESENT.value
    )
    
    # Set date range based on period
    today = date.today()
    
    if period == "daily":
        query = query.where(Attendance.date == today)
        group_by = "date"
    elif period == "weekly":
        # Get current week's Monday
        week_start = today - timedelta(days=today.weekday())
        query = query.where(
            Attendance.date >= week_start,
            Attendance.date <= today
        )
        group_by = "week_number"
    elif period == "monthly":
        month_start = date(today.year, today.month, 1)
        query = query.where(
            Attendance.date >= month_start,
            Attendance.date <= today
        )
        group_by = "month"
    elif period == "yearly":
        year_start = date(today.year, 1, 1)
        query = query.where(
            Attendance.date >= year_start,
            Attendance.date <= today
        )
        group_by = "year"
    else:
        raise HTTPException(status_code=400, detail="Invalid period")
    
    # Execute query
    attendances = session.exec(query).all()
    
    # Calculate totals
    total_minutes = sum(a.total_minutes or 0 for a in attendances)
    productive_minutes = sum(a.productive_minutes or 0 for a in attendances)
    break_minutes = sum(a._calculate_break_minutes() for a in attendances)
    overtime_minutes = sum(a.overtime_minutes or 0 for a in attendances)
    days_count = len(attendances)
    
    # Format response
    def format_hours(minutes: int) -> str:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"
    
    return {
        "period": period,
        "start_date": None,  # You can add date range calculation
        "end_date": today.isoformat(),
        "total_hours": format_hours(total_minutes),
        "productive_hours": format_hours(productive_minutes),
        "break_time": format_hours(break_minutes),
        "overtime": format_hours(overtime_minutes),
        "days_count": days_count,
        "average_daily_hours": format_hours(productive_minutes // days_count if days_count > 0 else 0),
        "attendance_count": len(attendances)
    }


# ============================================================
# ✅ COMPREHENSIVE ATTENDANCE TRACKING FOR ADMIN DASHBOARD
# ============================================================

@router.get("/tracking")
async def get_attendance_tracking(
    start_date: Optional[date] = Query(None, description="Start date (default: 7 days ago)"),
    end_date: Optional[date] = Query(None, description="End date (default: today)"),
    user_id: Optional[int] = Query(None, description="Filter by employee ID"),
    role: Optional[str] = Query(None, description="Filter by role"),
    location: Optional[str] = Query(None, description="Filter by location type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by name/email"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Get comprehensive attendance tracking data for admin dashboard.
    Shows ALL employees in the organization with their attendance records.
    """
    # Multi-tenant isolation - only access current organization data
    org_id = current_user.organization_id
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not associated with an organization"
        )
    
    # Set default date range (last 7 days)
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=7)
    if not end_date:
        end_date = today
    
    # Validate date range
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date"
        )
    
    # Get all active employees in the organization
    user_query = select(User).where(
        User.organization_id == org_id,
        User.is_active == True
    )
    
    if role:
        user_query = user_query.where(User.role == role)
    
    if search:
        search_filter = or_(
            User.full_name.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%")
        )
        user_query = user_query.where(search_filter)
    
    all_users = session.exec(user_query.order_by(User.full_name)).all()
    user_ids = [user.id for user in all_users]
    
    # If no users found
    if not user_ids:
        return {
            "success": True,
            "data": {
                "summary": {
                    "total_employees": 0,
                    "present_today": 0,
                    "on_leave": 0,
                    "late_arrivals": 0,
                    "avg_hours": 0
                },
                "records": [],
                "pagination": {
                    "current_page": page,
                    "total_pages": 0,
                    "total_records": 0,
                    "per_page": limit
                }
            }
        }
    
    # Get attendance records for the date range and filtered users
    attendance_query = select(Attendance).where(
        Attendance.organization_id == org_id,
        Attendance.user_id.in_(user_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    
    if user_id:
        attendance_query = attendance_query.where(Attendance.user_id == user_id)
    
    if status:
        attendance_query = attendance_query.where(Attendance.status == status)
    
    if location:
        attendance_query = attendance_query.where(Attendance.location == location)
    
    # Apply pagination
    total_records = session.exec(
        select(func.count()).select_from(attendance_query.subquery())
    ).one()
    
    total_pages = (total_records + limit - 1) // limit
    offset = (page - 1) * limit
    
    # Get paginated attendance records
    attendance_records = session.exec(
        attendance_query
        .order_by(desc(Attendance.date), desc(Attendance.check_in))
        .offset(offset)
        .limit(limit)
    ).all()
    
    # Get user map for quick lookup
    user_map = {user.id: user for user in all_users}
    
    # Get today's attendance for summary
    today_attendance = session.exec(
        select(Attendance).where(
            Attendance.organization_id == org_id,
            Attendance.date == today
        )
    ).all()
    
    # Calculate summary statistics
    present_today = len([a for a in today_attendance if a.status == "present"])
    late_today = len([a for a in today_attendance if a.is_late])
    
    # Calculate average hours (last 7 days)
    seven_days_ago = today - timedelta(days=7)
    recent_attendance = session.exec(
        select(Attendance).where(
            Attendance.organization_id == org_id,
            Attendance.date >= seven_days_ago,
            Attendance.date <= today,
            Attendance.status == "present"
        )
    ).all()
    
    total_hours_week = sum(a.total_minutes or 0 for a in recent_attendance) / 60
    avg_hours = total_hours_week / len(recent_attendance) if recent_attendance else 0
    
    # Prepare response records
    records = []
    for attendance in attendance_records:
        user = user_map.get(attendance.user_id)
        if not user:
            continue  # Skip if user not found (shouldn't happen)
        
        # Calculate weekly aggregates for this user
        week_start = attendance.date - timedelta(days=attendance.date.weekday())
        week_end = week_start + timedelta(days=6)
        
        weekly_records = session.exec(
            select(Attendance).where(
                Attendance.user_id == user.id,
                Attendance.organization_id == org_id,
                Attendance.date >= week_start,
                Attendance.date <= week_end
            )
        ).all()
        
        # Calculate weekly hours and attendance days
        weekly_hours_minutes = sum(r.total_minutes or 0 for r in weekly_records)
        weekly_attendance_days = sum(1 for r in weekly_records if r.status == "present")
        
        # Format break time for display
        break_display = "No breaks"
        if attendance.break_time and attendance.break_time != "00:00":
            hours, minutes = map(int, attendance.break_time.split(':'))
            if hours > 0:
                break_display = f"{hours}h {minutes}m"
            else:
                break_display = f"{minutes} min"
        
        # Determine status badge
        if attendance.status == "present":
            if attendance.is_late:
                status_badge = {"label": "Late", "color": "warning"}
            else:
                status_badge = {"label": "Present", "color": "success"}
        elif attendance.status == "absent":
            status_badge = {"label": "Absent", "color": "error"}
        elif attendance.status == "leave":
            status_badge = {"label": "On Leave", "color": "info"}
        else:
            status_badge = {"label": attendance.status.title(), "color": "default"}
        
        record_data = {
            "attendance_id": attendance.id,
            "user_id": user.id,
            "employee_name": user.full_name,
            "employee_email": user.email,
            "employee_role": user.role,
            "employee_avatar": user.profile_picture or f"https://ui-avatars.com/api/?name={user.full_name.replace(' ', '+')}&background=random",
            "date": attendance.date.isoformat(),
            "check_in_time": format_time_display(attendance.check_in),
            "check_out_time": format_time_display(attendance.check_out),
            "total_hours": attendance.total_hours or "00:00",
            "productive_hours": attendance.productive_hours or "00:00",
            "break_time": attendance.break_time or "00:00",  # Send raw HH:MM duration
            "overtime": attendance.overtime or "00:00",
            "work_location": attendance.location or "Not specified",
            "location_address": attendance.address or "Not tracked",
            "status": status_badge,
            "is_late": attendance.is_late,
            "notes": attendance.notes,
            "weekly_hours": format_minutes_to_time(weekly_hours_minutes),
            "weekly_attendance": f"{weekly_attendance_days}/5"
        }
        records.append(record_data)
    
    # Prepare response
    response = {
        "success": True,
        "data": {
            "summary": {
                "total_employees": len(all_users),
                "present_today": present_today,
                "on_leave": len([a for a in today_attendance if a.status == "leave"]),
                "late_arrivals": late_today,
                "avg_hours": round(avg_hours, 1)
            },
            "records": records,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_records": total_records,
                "per_page": limit
            }
        }
    }
    
    return response


@router.get("/employee/{employee_id}/history")
async def get_employee_attendance_history(
    employee_id: int,
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Get detailed attendance history for a specific employee.
    Admin can view any employee in their organization.
    """
    org_id = current_user.organization_id
    
    # Verify employee belongs to same organization
    employee = session.exec(
        select(User).where(
            User.id == employee_id,
            User.organization_id == org_id
        )
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found in your organization"
        )
    
    # Set default date range (last 30 days)
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today
    
    # Get attendance records
    records = session.exec(
        select(Attendance).where(
            Attendance.user_id == employee_id,
            Attendance.organization_id == org_id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        ).order_by(desc(Attendance.date))
    ).all()
    
    # Calculate monthly statistics
    monthly_stats = {}
    for record in records:
        month_key = f"{record.date.year}-{record.date.month:02d}"
        if month_key not in monthly_stats:
            monthly_stats[month_key] = {
                "total_days": 0,
                "present_days": 0,
                "absent_days": 0,
                "late_days": 0,
                "total_hours": 0,
                "productive_hours": 0
            }
        
        stats = monthly_stats[month_key]
        stats["total_days"] += 1
        
        if record.status == "present":
            stats["present_days"] += 1
            if record.is_late:
                stats["late_days"] += 1
            
            # Add hours
            if record.total_minutes:
                stats["total_hours"] += record.total_minutes / 60
            
            if record.productive_minutes:
                stats["productive_hours"] += record.productive_minutes / 60
        elif record.status == "absent":
            stats["absent_days"] += 1
    
    # Format response
    response = {
        "employee": {
            "id": employee.id,
            "full_name": employee.full_name,
            "email": employee.email,
            "role": employee.role,
            "department": employee.department,
            "job_title": employee.job_title
        },
        "date_range": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "summary": {
            "total_records": len(records),
            "present_count": sum(1 for r in records if r.status == "present"),
            "absent_count": sum(1 for r in records if r.status == "absent"),
            "late_count": sum(1 for r in records if r.is_late),
            "average_hours": sum(r.total_minutes or 0 for r in records) / 60 / len(records) if records else 0
        },
        "monthly_stats": monthly_stats,
        "attendance_records": [
            {
                "date": r.date.isoformat(),
                "check_in": r.check_in.strftime("%H:%M") if r.check_in else None,
                "check_out": r.check_out.strftime("%H:%M") if r.check_out else None,
                "total_hours": r.total_hours or "00:00",
                "productive_hours": r.productive_hours or "00:00",
                "break_time": r.break_time or "00:00",
                "overtime": r.overtime or "00:00",
                "location": r.location,
                "status": r.status,
                "is_late": r.is_late,
                "notes": r.notes,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "address": r.address
            }
            for r in records
        ]
    }
    
    return response


@router.get("/export/csv")
async def export_attendance_csv(
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Export attendance data as CSV for the organization.
    """
    org_id = current_user.organization_id
    
    # Set default date range (last 30 days)
    today = date.today()
    if not start_date:
        start_date = today - timedelta(days=30)
    if not end_date:
        end_date = today
    
    # Get all attendance records with user info
    from sqlmodel import join
    
    results = session.exec(
        select(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .where(
            Attendance.organization_id == org_id,
            User.organization_id == org_id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        .order_by(User.full_name, Attendance.date)
    ).all()
    
    # Prepare CSV data
    csv_data = []
    headers = [
        "Employee ID", "Employee Name", "Email", "Role", "Date",
        "Check In", "Check Out", "Total Hours", "Productive Hours",
        "Break Time", "Overtime", "Location", "Status", "Is Late",
        "Notes", "Address"
    ]
    
    for attendance, user in results:
        csv_data.append([
            user.id,
            user.full_name,
            user.email,
            user.role,
            attendance.date.isoformat(),
            attendance.check_in.strftime("%H:%M") if attendance.check_in else "",
            attendance.check_out.strftime("%H:%M") if attendance.check_out else "",
            attendance.total_hours or "00:00",
            attendance.productive_hours or "00:00",
            attendance.break_time or "00:00",
            attendance.overtime or "00:00",
            attendance.location or "",
            attendance.status,
            "Yes" if attendance.is_late else "No",
            attendance.notes or "",
            attendance.address or ""
        ])
    
    # Generate filename
    filename = f"attendance_export_{start_date}_{end_date}.csv"
    
    return {
        "filename": filename,
        "headers": headers,
        "data": csv_data
    }


# ============================================================
# ✅ EXPORT ENDPOINTS
# ============================================================
@router.get("/export")
async def export_attendance(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Export attendance data as CSV (Admin only)"""
    # Get attendance records
    records = session.exec(
        select(Attendance)
        .where(
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        .order_by(Attendance.date, Attendance.user_id)
    ).all()
    
    # Get user info
    users = session.exec(
        select(User)
        .where(User.organization_id == current_user.organization_id)
    ).all()
    user_dict = {user.id: user for user in users}
    
    # Prepare CSV data
    csv_data = []
    headers = ["Date", "Employee ID", "Employee Name", "Role", "Check In", 
               "Check Out", "Total Hours", "Location", "Status", "Late", "Overtime"]
    
    for record in records:
        user = user_dict.get(record.user_id)
        csv_data.append([
            record.date.isoformat(),
            record.user_id,
            user.full_name if user else "Unknown",
            user.job_title if user and user.job_title else user.role if user else "",
            record.check_in.strftime("%H:%M") if record.check_in else "",
            record.check_out.strftime("%H:%M") if record.check_out else "",
            record.total_hours or "",
            record.location or "",
            record.status,
            "Yes" if record.is_late else "No",
            record.overtime or ""
        ])
    
    return {
        "filename": f"attendance_{start_date}_{end_date}.csv",
        "headers": headers,
        "data": csv_data
    }


@router.get("/export-report")
async def export_attendance_report(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Export all users' attendance data as CSV string stream"""
    
    # Query all attendance records for the organization
    attendance_records = session.exec(
        select(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .where(Attendance.organization_id == current_user.organization_id)
        .order_by(desc(Attendance.date))
    ).all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # CSV Headers
    writer.writerow([
        'Employee ID', 'Employee Name', 'Date', 'Check-in Time', 
        'Check-out Time', 'Status', 'Hours Worked', 'Location'
    ])
    
    # Write data rows
    for attendance, user in attendance_records:
        writer.writerow([
            user.id,
            user.full_name or "Unknown",
            attendance.date,
            attendance.check_in.strftime("%H:%M") if attendance.check_in else "",
            attendance.check_out.strftime("%H:%M") if attendance.check_out else "",
            attendance.status,
            attendance.total_hours or 'N/A',
            attendance.location or 'N/A'
        ])
    
    # Prepare file for download
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=attendance-report-{datetime.now().date()}.csv"
        }
    )



# Helper function for weekly summary calculation
def calculate_weekly_summary(user_id: int, org_id: int, session: Session) -> dict:
    """Calculate weekly attendance summary for a user"""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get weekly attendance records
    weekly_records = session.exec(
        select(Attendance).where(
            Attendance.user_id == user_id,
            Attendance.organization_id == org_id,
            Attendance.date >= week_start,
            Attendance.date <= week_end
        )
    ).all()
    
    # Calculate totals
    total_minutes = sum(r.total_minutes or 0 for r in weekly_records)
    present_days = sum(1 for r in weekly_records if r.status == "present")
    late_days = sum(1 for r in weekly_records if r.is_late)
    
    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_hours": format_minutes_to_time(total_minutes),
        "present_days": present_days,
        "late_days": late_days,
        "attendance_percentage": (present_days / 5 * 100) if present_days > 0 else 0
    }