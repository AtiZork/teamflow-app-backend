# routes/timesheet.py
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func, and_, or_
from sqlalchemy.orm import joinedload

from core.database import get_session
from models.models import Timesheet, TimesheetStatus
from models.models import User, Task, Project, TaskMemberLink, Organization, TaskWorkLog
from schemas.timesheet_schema import (
    TimesheetCreate, TimesheetRead, TimesheetUpdate, 
    WeeklyTimesheetSummary, DailyTimesheetEntry,
    TimesheetBulkCreate, UserTaskWeekResponse, UserTaskDay
)
from core.security import get_current_user, get_current_admin

router = APIRouter(prefix="/timesheet", tags=["timesheet"])


def get_week_dates(target_date: date) -> tuple[date, date]:
    """Get week start (Monday) and end (Sunday) for a given date"""
    weekday = target_date.weekday()  # Monday=0, Sunday=6
    week_start = target_date - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start, week_end


def get_current_week_dates() -> tuple[date, date]:
    """Get current week Monday to Sunday"""
    today = date.today()
    return get_week_dates(today)


@router.get("/user-tasks", response_model=UserTaskWeekResponse)
def get_user_tasks_for_week(
    user_id: Optional[int] = Query(None, description="User ID to filter by"),
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get all tasks assigned to a user for a specific week (Monday to Sunday)
    Returns tasks grouped by day with project information
    """
    # Calculate week dates
    if not week_start:
        week_start, week_end = get_current_week_dates()
    else:
        week_start, week_end = get_week_dates(week_start)
    
    # Determine which user to query
    target_user_id = user_id if user_id else current_user.id
    
    # Verify user exists and belongs to organization
    user = session.exec(
        select(User).where(
            User.id == target_user_id,
            User.organization_id == organization_id
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")
    
    # Get all tasks assigned to this user
    tasks_query = (
        select(Task)
        .join(TaskMemberLink, TaskMemberLink.task_id == Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskMemberLink.user_id == target_user_id,
            Task.organization_id == organization_id,
            Project.organization_id == organization_id
        )
        .options(joinedload(Task.project))
    )
    
    tasks = session.exec(tasks_query).all()
    
    # Structure response by day
    daily_tasks = {}
    
    # Initialize all days in the week
    for day_offset in range(7):  # Monday to Sunday
        current_date = week_start + timedelta(days=day_offset)
        daily_tasks[current_date] = []
    
    # Assign tasks to days (for now, all tasks are shown every day)
    # You can modify this logic based on your business rules
    for task in tasks:
        # For demonstration, show task every day of the week
        # In real implementation, you might want to filter by due_date, created_at, etc.
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            
            task_data = UserTaskDay(
                task_id=task.id,
                task_title=task.title,
                task_description=task.description,
                project_id=task.project_id,
                project_name=task.project.title if task.project else None,
                status=task.status,
                priority=task.priority,
                due_date=task.due_date,
                estimated_hours=0.0,  # You might want to add this field to Task model
                logged_hours=0.0,     # Calculate from work logs
                is_completed=task.status.lower() in ['done', 'completed', 'closed']
            )
            daily_tasks[current_date].append(task_data)
    
    # Calculate total hours per day and week
    daily_totals = {}
    week_total_hours = 0.0
    
    for day_date, day_tasks in daily_tasks.items():
        day_total = sum(task.logged_hours for task in day_tasks)
        daily_totals[day_date] = day_total
        week_total_hours += day_total
    
    response = UserTaskWeekResponse(
        user_id=user.id,
        user_name=user.full_name,
        week_start=week_start,
        week_end=week_end,
        daily_tasks=daily_tasks,
        daily_totals=daily_totals,
        week_total_hours=week_total_hours,
        total_tasks=len(tasks)
    )
    
    return response


@router.get("/user-worklogs", response_model=UserTaskWeekResponse)
def get_user_tasks_with_worklogs(
    user_id: Optional[int] = Query(None, description="User ID to filter by"),
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get tasks with actual work log hours for a specific week
    More accurate than the basic version as it uses actual work logs
    """
    from models.models import TaskWorkLog
    
    # Calculate week dates
    if not week_start:
        week_start, week_end = get_current_week_dates()
    else:
        week_start, week_end = get_week_dates(week_start)
    
    # Determine which user to query
    target_user_id = user_id if user_id else current_user.id
    
    # Verify user exists and belongs to organization
    user = session.exec(
        select(User).where(
            User.id == target_user_id,
            User.organization_id == organization_id
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")
    
    # Get work logs for the user in the specified week
    work_logs_query = (
        select(TaskWorkLog)
        .join(Task, Task.id == TaskWorkLog.task_id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskWorkLog.user_id == target_user_id,
            TaskWorkLog.date >= week_start,
            TaskWorkLog.date <= week_end,
            TaskWorkLog.organization_id == organization_id
        )
        .options(joinedload(TaskWorkLog.task).joinedload(Task.project))
    )
    
    work_logs = session.exec(work_logs_query).all()
    
    # Structure response by day
    daily_tasks = {}
    daily_totals = {}
    
    # Initialize all days in the week
    for day_offset in range(7):
        current_date = week_start + timedelta(days=day_offset)
        daily_tasks[current_date] = []
        daily_totals[current_date] = 0.0
    
    # Group work logs by task and date
    task_work_data = {}
    
    for work_log in work_logs:
        task_date = work_log.date.date() if isinstance(work_log.date, datetime) else work_log.date
        task_key = (work_log.task_id, task_date)
        
        if task_key not in task_work_data:
            task_work_data[task_key] = {
                'task': work_log.task,
                'hours': 0.0,
                'date': task_date
            }
        
        task_work_data[task_key]['hours'] += work_log.hours
    
    # Populate daily tasks
    for (task_id, task_date), data in task_work_data.items():
        task = data['task']
        
        task_data = UserTaskDay(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            project_id=task.project_id,
            project_name=task.project.title if task.project else None,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
            estimated_hours=0.0,
            logged_hours=data['hours'],
            is_completed=task.status.lower() in ['done', 'completed', 'closed']
        )
        
        daily_tasks[task_date].append(task_data)
        daily_totals[task_date] += data['hours']
    
    # Also include tasks without work logs but assigned to user
    assigned_tasks_query = (
        select(Task)
        .join(TaskMemberLink, TaskMemberLink.task_id == Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskMemberLink.user_id == target_user_id,
            Task.organization_id == organization_id
        )
        .options(joinedload(Task.project))
    )
    
    assigned_tasks = session.exec(assigned_tasks_query).all()
    
    for task in assigned_tasks:
        # Check if task already exists in any day
        task_exists = any(
            any(t.task_id == task.id for t in day_tasks)
            for day_tasks in daily_tasks.values()
        )
        
        if not task_exists:
            # Add task to Monday as default
            monday_date = week_start
            task_data = UserTaskDay(
                task_id=task.id,
                task_title=task.title,
                task_description=task.description,
                project_id=task.project_id,
                project_name=task.project.title if task.project else None,
                status=task.status,
                priority=task.priority,
                due_date=task.due_date,
                estimated_hours=0.0,
                logged_hours=0.0,
                is_completed=task.status.lower() in ['done', 'completed', 'closed']
            )
            daily_tasks[monday_date].append(task_data)
    
    # Calculate week total
    week_total_hours = sum(daily_totals.values())
    total_tasks = sum(len(day_tasks) for day_tasks in daily_tasks.values())
    
    response = UserTaskWeekResponse(
        user_id=user.id,
        user_name=user.full_name,
        week_start=week_start,
        week_end=week_end,
        daily_tasks=daily_tasks,
        daily_totals=daily_totals,
        week_total_hours=week_total_hours,
        total_tasks=total_tasks
    )
    
    return response


# Keep existing routes but update week calculation to Monday-Sunday
@router.get("/", response_model=List[TimesheetRead])
def get_timesheets(
    skip: int = 0,
    limit: int = 100,
    user_id: Optional[int] = None,
    department: Optional[str] = None,
    week_start: Optional[date] = None,
    organization_id: int = Query(..., description="Organization ID"),
    session: Session = Depends(get_session)
):
    """Get timesheets with filtering options"""
    query = select(Timesheet).where(Timesheet.organization_id == organization_id)
    
    if user_id:
        query = query.where(Timesheet.user_id == user_id)
    
    if week_start:
        week_start, week_end = get_week_dates(week_start)
        query = query.where(Timesheet.week_start == week_start)
    
    if department:
        query = query.join(User).where(User.department == department)
    
    query = query.offset(skip).limit(limit)
    timesheets = session.exec(query).all()
    return timesheets


@router.get("/summary", response_model=List[WeeklyTimesheetSummary])
def get_timesheet_summary(
    department: Optional[str] = Query(None, description="Filter by department"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    organization_id: int = Query(..., description="Organization ID"),
    session: Session = Depends(get_session)
):
    """
    Get weekly timesheet summary per employee
    If no week_start provided, uses current week (Monday to Sunday)
    """
    # Calculate week dates
    if not week_start:
        week_start, week_end = get_current_week_dates()
    else:
        week_start, week_end = get_week_dates(week_start)
    
    # Build base query (rest of the function remains similar but with updated week range)
    query = (
        select(
            User.id,
            User.full_name,
            User.job_title,
            User.department,
            func.coalesce(func.sum(Timesheet.working_hours), 0).label("total_working_hours"),
            func.coalesce(func.sum(Timesheet.task_hours), 0).label("total_task_hours")
        )
        .select_from(User)
        .outerjoin(
            Timesheet,
            and_(
                Timesheet.user_id == User.id,
                Timesheet.week_start == week_start,
                Timesheet.organization_id == organization_id
            )
        )
        .where(User.organization_id == organization_id)
        .group_by(User.id, User.full_name, User.job_title, User.department)
    )
    
    # Apply filters
    if department:
        query = query.where(User.department == department)
    
    if user_id:
        query = query.where(User.id == user_id)
    
    # Execute query
    results = session.exec(query).all()
    
    # Build response with daily breakdown (7 days now)
    summaries = []
    for result in results:
        # Get daily entries for this user and week
        daily_query = (
            select(Timesheet)
            .where(
                Timesheet.user_id == result.id,
                Timesheet.week_start == week_start,
                Timesheet.organization_id == organization_id
            )
        )
        daily_entries = session.exec(daily_query).all()
        
        # Create daily entries list (7 days)
        daily_data = []
        for day in range(7):  # Monday to Sunday
            current_date = week_start + timedelta(days=day)
            entry = next(
                (e for e in daily_entries if e.date.date() == current_date), 
                None
            )
            if entry:
                daily_data.append(DailyTimesheetEntry(
                    date=current_date,
                    working_hours=entry.working_hours,
                    task_hours=entry.task_hours,
                    status=entry.status
                ))
            else:
                # Default entry for days without data
                daily_data.append(DailyTimesheetEntry(
                    date=current_date,
                    working_hours=8.0 if day < 5 else 0.0,  # 8 hours weekdays, 0 weekends
                    task_hours=0.0,
                    status="draft"
                ))
        
        summary = WeeklyTimesheetSummary(
            user_id=result.id,
            full_name=result.full_name,
            job_title=result.job_title or "",
            department=result.department,
            week_start=week_start,
            week_end=week_end,
            total_working_hours=result.total_working_hours or 0.0,
            total_task_hours=result.total_task_hours or 0.0,
            daily_entries=daily_data
        )
        summaries.append(summary)
    
    return summaries



# Add to routes/timesheet.py

@router.get("/worklogs/summary", response_model=Dict)
def get_worklogs_summary(
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    custom_start: Optional[date] = Query(None, description="Custom range start"),
    custom_end: Optional[date] = Query(None, description="Custom range end"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get worklogs summary for TWH and TTT calculations
    Supports week-based or custom date range
    """
    from datetime import datetime
    
    # Determine date range
    if custom_start and custom_end:
        # Custom date range
        start_date = custom_start
        end_date = custom_end
        range_type = "custom"
    else:
        # Week-based range (default to current week)
        if not week_start:
            week_start, week_end = get_current_week_dates()
        else:
            week_start, week_end = get_week_dates(week_start)
        start_date = week_start
        end_date = week_end
        range_type = "week"
    
    # Convert to datetime for query
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    
    # Get TWH - Total Weekly Hours (sum of all work logs in range)
    twh_query = (
        select(func.sum(TaskWorkLog.hours))
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= start_datetime,
            TaskWorkLog.date <= end_datetime
        )
    )
    total_weekly_hours = session.exec(twh_query).first() or 0.0
    
    # Get TTT - Today's Task Time (current day only)
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    ttt_query = (
        select(func.sum(TaskWorkLog.hours))
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= today_start,
            TaskWorkLog.date <= today_end
        )
    )
    todays_task_time = session.exec(ttt_query).first() or 0.0
    
    # Get daily breakdown for the range
    daily_breakdown_query = (
        select(
            func.date(TaskWorkLog.date).label("work_date"),
            func.sum(TaskWorkLog.hours).label("daily_hours")
        )
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= start_datetime,
            TaskWorkLog.date <= end_datetime
        )
        .group_by(func.date(TaskWorkLog.date))
    )
    
    daily_results = session.exec(daily_breakdown_query).all()
    daily_breakdown = {str(result.work_date): result.daily_hours for result in daily_results}
    
    return {
        "total_weekly_hours": float(total_weekly_hours),
        "todays_task_time": float(todays_task_time),
        "date_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "type": range_type
        },
        "daily_breakdown": daily_breakdown
    }

@router.get("/worklogs/daily-tasks")
def get_daily_tasks(
    target_date: date = Query(..., description="Specific date to get tasks for"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get tasks for a specific day with priority information
    """
    target_start = datetime.combine(target_date, datetime.min.time())
    target_end = datetime.combine(target_date, datetime.max.time())
    
    tasks_query = (
        select(TaskWorkLog, Task)
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= target_start,
            TaskWorkLog.date <= target_end
        )
        .options(joinedload(TaskWorkLog.task))
    )
    
    results = session.exec(tasks_query).all()
    
    daily_tasks = []
    for worklog, task in results:
        daily_tasks.append({
            "task_id": task.id,
            "task_title": task.title,
            "priority": task.priority,
            "logged_hours": worklog.hours,
            "description": worklog.description
        })
    
    return {
        "date": target_date.isoformat(),
        "tasks": daily_tasks,
        "total_hours": sum(task["logged_hours"] for task in daily_tasks)
    }




# In timesheet.py - Update the is_task_active_on_date function
def is_task_active_on_date(task, target_date):
    """
    Check if a task should be displayed on a specific date based on start_date and due_date
    """
    # Use start_date if available (new field), otherwise fall back to assigned_date/created_at
    start_date = getattr(task, 'start_date', None)
    if not start_date:
        assigned_date = getattr(task, 'assigned_date', None)
        if not assigned_date and hasattr(task, 'created_at'):
            assigned_date = task.created_at.date() if task.created_at else None
        start_date = assigned_date
    
    # If still no start_date, show task for all dates (fallback)
    if not start_date:
        return True
    
    # Handle date conversions
    start_date = start_date.date() if isinstance(start_date, datetime) else start_date
    target_date = target_date.date() if isinstance(target_date, datetime) else target_date
    
    # Check if target_date is within start_date and due_date range
    if task.due_date:
        due_date = task.due_date.date() if isinstance(task.due_date, datetime) else task.due_date
        return start_date <= target_date <= due_date
    
    # If no due_date, only show from start_date onwards
    return target_date >= start_date


# Now update the get_filtered_user_tasks route in routes/timesheet.py:
@router.get("/filtered-tasks", response_model=UserTaskWeekResponse)
def get_filtered_user_tasks(
    user_id: Optional[int] = Query(None, description="User ID to filter by"),
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get tasks for user with proper date filtering - tasks appear from assigned_date to due_date
    """
    from datetime import datetime
    
    # Calculate week dates
    if not week_start:
        week_start, week_end = get_current_week_dates()
    else:
        week_start, week_end = get_week_dates(week_start)
    
    # Determine which user to query
    target_user_id = user_id if user_id else current_user.id
    
    # Verify user exists and belongs to organization
    user = session.exec(
        select(User).where(
            User.id == target_user_id,
            User.organization_id == organization_id
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")
    
    # Get current date for filtering future dates
    current_date = datetime.utcnow().date()
    
    # Get all tasks assigned to this user
    tasks_query = (
        select(Task)
        .join(TaskMemberLink, TaskMemberLink.task_id == Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskMemberLink.user_id == target_user_id,
            Task.organization_id == organization_id,
            Project.organization_id == organization_id
        )
        .options(joinedload(Task.project))
    )
    
    tasks = session.exec(tasks_query).all()
    
    # Get work logs for accurate time tracking
    work_logs_query = (
        select(TaskWorkLog)
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.user_id == target_user_id,
            TaskWorkLog.date >= week_start,
            TaskWorkLog.date <= week_end,
            TaskWorkLog.organization_id == organization_id
        )
    )
    
    work_logs = session.exec(work_logs_query).all()
    
    # Structure response by day with proper date range filtering
    daily_tasks = {}
    daily_totals = {}
    
    # Initialize all days in the week
    for day_offset in range(7):  # Monday to Sunday
        current_day_date = week_start + timedelta(days=day_offset)
        daily_tasks[current_day_date] = []
        daily_totals[current_day_date] = 0.0
        
        # For each day, determine which tasks should be displayed
        for task in tasks:
            # Check if task should be active on this date based on assigned_date and due_date
            if is_task_active_on_date(task, current_day_date):
                # Get work logs for this specific day and task
                day_task_work_logs = [
                    wl for wl in work_logs 
                    if wl.date.date() == current_day_date and wl.task_id == task.id
                ]
                
                # Calculate total hours for this task on this day
                task_hours = sum(wl.hours for wl in day_task_work_logs)
                
                task_data = UserTaskDay(
                    task_id=task.id,
                    task_title=task.title,
                    task_description=task.description,
                    project_id=task.project_id,
                    project_name=task.project.title if task.project else None,
                    status=task.status,
                    priority=task.priority,
                    due_date=task.due_date,
                    estimated_hours=task.estimated_hours if hasattr(task, 'estimated_hours') else 0.0,
                    logged_hours=task_hours,
                    is_completed=task.status.lower() in ['done', 'completed', 'closed']
                )
                
                daily_tasks[current_day_date].append(task_data)
                daily_totals[current_day_date] += task_hours
    
    # Calculate week total
    week_total_hours = sum(daily_totals.values())
    total_tasks = sum(len(day_tasks) for day_tasks in daily_tasks.values())
    
    response = UserTaskWeekResponse(
        user_id=user.id,
        user_name=user.full_name,
        week_start=week_start,
        week_end=week_end,
        daily_tasks=daily_tasks,
        daily_totals=daily_totals,
        week_total_hours=week_total_hours,
        total_tasks=total_tasks
    )
    
    return response




@router.get("/worklogs/employee-summary")
def getWorklogsSummary(
    user_id: Optional[int] = Query(None, description="User ID to filter by"),
    week_start: Optional[date] = Query(None, description="Week start date (Monday)"),
    organization_id: int = Query(..., description="Organization ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get worklogs summary for specific employee with TWH and TTT calculations
    """
    from datetime import datetime
    
    # Calculate week dates
    if not week_start:
        week_start, week_end = get_current_week_dates()
    else:
        week_start, week_end = get_week_dates(week_start)
    
    # Determine which user to query
    target_user_id = user_id if user_id else current_user.id
    
    # Verify user exists and belongs to organization
    user = session.exec(
        select(User).where(
            User.id == target_user_id,
            User.organization_id == organization_id
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found in organization")
    
    # Convert to datetime for query
    start_datetime = datetime.combine(week_start, datetime.min.time())
    end_datetime = datetime.combine(week_end, datetime.max.time())
    
    # Get TWH - Total Weekly Hours (sum of all work logs in the week)
    twh_query = (
        select(func.sum(TaskWorkLog.hours))
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.user_id == target_user_id,
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= start_datetime,
            TaskWorkLog.date <= end_datetime
        )
    )
    total_weekly_hours = session.exec(twh_query).first() or 0.0
    
    # Get TTT - Today's Task Time (current day only for this user)
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    ttt_query = (
        select(func.sum(TaskWorkLog.hours))
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.user_id == target_user_id,
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= today_start,
            TaskWorkLog.date <= today_end
        )
    )
    todays_task_time = session.exec(ttt_query).first() or 0.0
    
    # Get daily breakdown for the week
    daily_breakdown_query = (
        select(
            func.date(TaskWorkLog.date).label("work_date"),
            func.sum(TaskWorkLog.hours).label("daily_hours")
        )
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.user_id == target_user_id,
            TaskWorkLog.organization_id == organization_id,
            TaskWorkLog.date >= start_datetime,
            TaskWorkLog.date <= end_datetime
        )
        .group_by(func.date(TaskWorkLog.date))
    )
    
    daily_results = session.exec(daily_breakdown_query).all()
    daily_breakdown = {str(result.work_date): float(result.daily_hours) for result in daily_results}
    
    return {
        "user_id": user.id,
        "user_name": user.full_name,
        "total_work_hours": float(total_weekly_hours),  # TWH
        "total_task_time": float(todays_task_time),     # TTT
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "daily_breakdown": daily_breakdown
    }





