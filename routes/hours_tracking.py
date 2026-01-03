# Create a new file: routes/hours_tracking.py

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from sqlmodel import Session, select, func, and_, or_
import calendar

from core.database import get_session
from core.security import get_current_user, get_current_admin
from models.models import User
from models.attendance_models import Attendance
from schemas.hours_schema import (
    EmployeeHours, DailyHours, WeeklySummary, MonthlySummary,
    EmployeeHoursSummary, HoursReportRequest, HoursPeriod
)

router = APIRouter(prefix="/hours", tags=["hours-tracking"])


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


@router.get("/today", response_model=Dict[str, str])
async def get_today_hours(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get today's hours for current user"""
    today = date.today()
    
    attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    if not attendance:
        return {
            "total_hours": "00:00",
            "productive_hours": "00:00",
            "break_time": "00:00",
            "overtime": "00:00"
        }
    
    return {
        "total_hours": attendance.total_hours or "00:00",
        "productive_hours": attendance.productive_hours or "00:00",
        "break_time": attendance.break_time or "00:00",
        "overtime": attendance.overtime or "00:00"
    }


@router.get("/weekly", response_model=WeeklySummary)
async def get_weekly_hours(
    week_start: Optional[date] = Query(None, description="Start of week (default: current week)"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get weekly hours summary for current user"""
    today = date.today()
    
    # Calculate week start and end
    if week_start:
        week_start_date = week_start
    else:
        # Start from Monday
        week_start_date = today - timedelta(days=today.weekday())
    
    week_end_date = week_start_date + timedelta(days=6)
    
    # Get all attendance records for the week
    attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= week_start_date,
            Attendance.date <= week_end_date
        )
        .order_by(Attendance.date)
    ).all()
    
    # Calculate totals
    total_minutes = 0
    productive_minutes = 0
    break_minutes = 0
    overtime_minutes = 0
    working_dates = set()
    
    days_list = []
    
    for attendance in attendances:
        if attendance.status == "present" and attendance.total_hours:
            total_minutes += parse_time_to_minutes(attendance.total_hours)
            productive_minutes += parse_time_to_minutes(attendance.productive_hours or "00:00")
            break_minutes += parse_time_to_minutes(attendance.break_time or "00:00")
            overtime_minutes += parse_time_to_minutes(attendance.overtime or "00:00")
            working_dates.add(attendance.date)
        
        # Add day details
        
        # Add day details
        days_list.append(DailyHours(
            date=attendance.date,
            day_name=attendance.date.strftime("%A"),
            check_in=attendance.check_in.strftime("%H:%M") if attendance.check_in else None,
            check_out=attendance.check_out.strftime("%H:%M") if attendance.check_out else None,
            total_hours=attendance.total_hours or "00:00",
            productive_hours=attendance.productive_hours or "00:00",
            break_time=attendance.break_time or "00:00",
            overtime=attendance.overtime or "00:00",
            status=attendance.status,
            location=attendance.location
        ))
    
    working_days = len(working_dates)

    # Calculate average daily hours
    avg_daily_minutes = productive_minutes // working_days if working_days > 0 else 0
    
    return WeeklySummary(
        week_number=week_start_date.isocalendar()[1],
        week_start=week_start_date,
        week_end=week_end_date,
        total_hours=format_minutes_to_time(total_minutes),
        productive_hours=format_minutes_to_time(productive_minutes),
        average_daily_hours=format_minutes_to_time(avg_daily_minutes),
        overtime_total=format_minutes_to_time(overtime_minutes),
        working_days=working_days,
        days=days_list
    )


@router.get("/monthly", response_model=MonthlySummary)
async def get_monthly_hours(
    month_year: Optional[str] = Query(None, description="Month in YYYY-MM format (default: current month)"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get monthly hours summary for current user"""
    today = date.today()
    
    if month_year:
        year, month = map(int, month_year.split('-'))
    else:
        year, month = today.year, today.month
    
    # Calculate month start and end
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    
    # Get all attendance records for the month
    attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= month_start,
            Attendance.date <= month_end
        )
        .order_by(Attendance.date)
    ).all()
    
    # Calculate totals
    # Calculate totals
    total_minutes = 0
    productive_minutes = 0
    overtime_minutes = 0
    working_dates = set()
    absent_days = 0
    leave_days = 0
    late_days = 0
    
    # Group by week for weekly breakdown
    weeks_dict = {}
    weekly_summaries = []
    
    for attendance in attendances:
        week_num = attendance.date.isocalendar()[1]
        if week_num not in weeks_dict:
            weeks_dict[week_num] = []
        weeks_dict[week_num].append(attendance)
        
        # Count days by status
        if attendance.status == "present":
            working_dates.add(attendance.date)
            if attendance.is_late:
                late_days += 1
        elif attendance.status == "absent":
            absent_days += 1
        elif attendance.status == "leave":
            leave_days += 1
        
        # Add to totals if present
        if attendance.status == "present":
            total_minutes += parse_time_to_minutes(attendance.total_hours or "00:00")
            productive_minutes += parse_time_to_minutes(attendance.productive_hours or "00:00")
            overtime_minutes += parse_time_to_minutes(attendance.overtime or "00:00")
            
    working_days = len(working_dates)
    
    # Create weekly summaries
    for week_num, week_attendances in weeks_dict.items():
        week_start = min([a.date for a in week_attendances])
        week_end = max([a.date for a in week_attendances])
        
        week_total = 0
        week_productive = 0
        week_working_dates = set()
        
        for att in week_attendances:
            if att.status == "present":
                week_total += parse_time_to_minutes(att.total_hours or "00:00")
                week_productive += parse_time_to_minutes(att.productive_hours or "00:00")
                week_working_dates.add(att.date)
        
        week_days = len(week_working_dates)
        
        avg_daily = week_productive // week_days if week_days > 0 else 0
        
        weekly_summaries.append(WeeklySummary(
            week_number=week_num,
            week_start=week_start,
            week_end=week_end,
            total_hours=format_minutes_to_time(week_total),
            productive_hours=format_minutes_to_time(week_productive),
            average_daily_hours=format_minutes_to_time(avg_daily),
            overtime_total="00:00",  # Can be calculated separately
            working_days=week_days,
            days=[]
        ))
    
    # Calculate averages
    avg_daily_minutes = productive_minutes // working_days if working_days > 0 else 0
    
    return MonthlySummary(
        month_year=f"{year:04d}-{month:02d}",
        month_name=month_start.strftime("%B %Y"),
        total_hours=format_minutes_to_time(total_minutes),
        productive_hours=format_minutes_to_time(productive_minutes),
        average_daily_hours=format_minutes_to_time(avg_daily_minutes),
        overtime_total=format_minutes_to_time(overtime_minutes),
        working_days=working_days,
        absent_days=absent_days,
        leave_days=leave_days,
        late_days=late_days,
        weekly_breakdown=weekly_summaries
    )


@router.get("/employee/summary", response_model=EmployeeHoursSummary)
async def get_employee_hours_summary(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get comprehensive hours summary for current employee"""
    # Get today's hours
    today = date.today()
    today_attendance = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.date == today,
            Attendance.organization_id == current_user.organization_id
        )
    ).first()
    
    today_hours = None
    if today_attendance:
            today_hours = DailyHours(
            date=today,
            day_name=today.strftime("%A"),
            check_in=today_attendance.check_in.strftime("%H:%M") if today_attendance.check_in else None,
            check_out=today_attendance.check_out.strftime("%H:%M") if today_attendance.check_out else None,
            total_hours=today_attendance.total_hours or "00:00",
            productive_hours=today_attendance.productive_hours or "00:00",
                break_time=today_attendance.break_time or "00:00",
            overtime=today_attendance.overtime or "00:00",
            status=today_attendance.status,
            location=today_attendance.location
        )
    
    # Get current week summary
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    week_attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= week_start,
            Attendance.date <= week_end
        )
    ).all()
    
    week_total = 0
    week_productive = 0
    week_break = 0
    week_overtime = 0
    week_working_dates = set()
    
    for att in week_attendances:
            if att.status == "present":
                week_total += parse_time_to_minutes(att.total_hours or "00:00")
                week_productive += parse_time_to_minutes(att.productive_hours or "00:00")
                week_break += parse_time_to_minutes(att.break_time or "00:00")
                week_overtime += parse_time_to_minutes(att.overtime or "00:00")
                week_working_dates.add(att.date)
            
    week_days = len(week_working_dates)
    
    avg_daily = week_productive // week_days if week_days > 0 else 0
    
    current_week = WeeklySummary(
        week_number=week_start.isocalendar()[1],
        week_start=week_start,
        week_end=week_end,
        total_hours=format_minutes_to_time(week_total),
        productive_hours=format_minutes_to_time(week_productive),
        average_daily_hours=format_minutes_to_time(avg_daily),
        overtime_total=format_minutes_to_time(week_overtime),
        working_days=week_days,
        days=[]
    )
    
    # Get current month summary
    month_start = date(today.year, today.month, 1)
    month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    
    month_attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= month_start,
            Attendance.date <= month_end
        )
    ).all()
    
    month_total = 0
    month_productive = 0
    month_overtime = 0
    month_working_dates = set()
    
    for att in month_attendances:
        if att.status == "present":
            month_total += parse_time_to_minutes(att.total_hours or "00:00")
            month_productive += parse_time_to_minutes(att.productive_hours or "00:00")
            month_overtime += parse_time_to_minutes(att.overtime or "00:00")
            month_working_dates.add(att.date)
            if att.is_late:
                late_days += 1
        elif att.status == "absent":
            absent_days += 1
        elif att.status == "leave":
            leave_days += 1
            
    month_days = len(month_working_dates)
    
    avg_monthly_daily = month_productive // month_days if month_days > 0 else 0
    
    current_month = MonthlySummary(
        month_year=month_start.strftime("%Y-%m"),
        month_name=month_start.strftime("%B %Y"),
        total_hours=format_minutes_to_time(month_total),
        productive_hours=format_minutes_to_time(month_productive),
        average_daily_hours=format_minutes_to_time(avg_monthly_daily),
        overtime_total=format_minutes_to_time(month_overtime),
        working_days=month_days,
        absent_days=absent_days,
        leave_days=leave_days,
        late_days=late_days,
        weekly_breakdown=[]
    )
    
    # Year to date stats
    year_start = date(today.year, 1, 1)
    ytd_attendances = session.exec(
        select(Attendance)
        .where(
            Attendance.user_id == current_user.id,
            Attendance.organization_id == current_user.organization_id,
            Attendance.date >= year_start,
            Attendance.date <= today
        )
    ).all()
    
    ytd_total = 0
    ytd_productive = 0
    ytd_overtime = 0
    ytd_working_dates = set()
    
    for att in ytd_attendances:
        if att.status == "present":
            ytd_total += parse_time_to_minutes(att.total_hours or "00:00")
            ytd_productive += parse_time_to_minutes(att.productive_hours or "00:00")
            ytd_overtime += parse_time_to_minutes(att.overtime or "00:00")
            ytd_working_dates.add(att.date)
            
    ytd_days = len(ytd_working_dates)
    
    return EmployeeHoursSummary(
        employee_id=current_user.id,
        employee_name=current_user.full_name,
        today_hours=today_hours,
        current_week=current_week,
        current_month=current_month,
        year_to_date={
            "total_hours": format_minutes_to_time(ytd_total),
            "productive_hours": format_minutes_to_time(ytd_productive),
            "overtime": format_minutes_to_time(ytd_overtime),
            "working_days": str(ytd_days),
            "average_daily_hours": format_minutes_to_time(ytd_productive // ytd_days if ytd_days > 0 else 0)
        }
    )


@router.get("/organization", response_model=List[EmployeeHours])
async def get_organization_hours(
    period: HoursPeriod = Query(HoursPeriod.MONTHLY, description="Time period"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Get hours report for all employees in organization (Admin only)"""
    today = date.today()
    
    # Set date range based on period
    if period == HoursPeriod.DAILY:
        if not start_date:
            start_date = today
        if not end_date:
            end_date = today
    elif period == HoursPeriod.WEEKLY:
        if not start_date:
            start_date = today - timedelta(days=today.weekday())
        if not end_date:
            end_date = start_date + timedelta(days=6)
    elif period == HoursPeriod.MONTHLY:
        if not start_date:
            start_date = date(today.year, today.month, 1)
        if not end_date:
            end_date = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    else:  # YEARLY
        if not start_date:
            start_date = date(today.year, 1, 1)
        if not end_date:
            end_date = date(today.year, 12, 31)
    
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
        # Get user's attendance for the period
        attendances = session.exec(
            select(Attendance)
            .where(
                Attendance.user_id == user.id,
                Attendance.organization_id == current_user.organization_id,
                Attendance.date >= start_date,
                Attendance.date <= end_date,
                Attendance.status == "present"
            )
        ).all()
        
        # Calculate totals
        total_minutes = 0
        productive_minutes = 0
        break_minutes = 0
        overtime_minutes = 0
        working_days = len({att.date for att in attendances})
        
        for att in attendances:
            total_minutes += parse_time_to_minutes(att.total_hours or "00:00")
            productive_minutes += parse_time_to_minutes(att.productive_hours or "00:00")
            break_minutes += parse_time_to_minutes(att.break_time or "00:00")
            overtime_minutes += parse_time_to_minutes(att.overtime or "00:00")
        
        # Calculate average daily hours
        avg_daily = productive_minutes // working_days if working_days > 0 else 0
        
        result.append(EmployeeHours(
            employee_id=user.id,
            employee_name=user.full_name,
            employee_role=user.job_title or user.role,
            total_hours=format_minutes_to_time(total_minutes),
            productive_hours=format_minutes_to_time(productive_minutes),
            break_time=format_minutes_to_time(break_minutes),
            overtime=format_minutes_to_time(overtime_minutes),
            working_days=working_days,
            average_daily_hours=format_minutes_to_time(avg_daily)
        ))
    
    return result