# schemas/timesheet.py
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
from sqlmodel import SQLModel


# Base schemas
class TimesheetBase(SQLModel):
    user_id: int
    task_id: Optional[int] = None
    date: datetime  # Changed from date to datetime
    working_hours: float = 0.0
    task_hours: float = 0.0
    description: Optional[str] = None
    status: str = "draft"

# Update all other schemas similarly...


class TimesheetCreate(TimesheetBase):
    organization_id: int


class TimesheetUpdate(SQLModel):
    working_hours: Optional[float] = None
    task_hours: Optional[float] = None
    description: Optional[str] = None
    status: Optional[str] = None


# Response schemas with related data
class TimesheetUser(SQLModel):
    id: int
    full_name: str
    email: str
    department: Optional[str]
    job_title: Optional[str]


class TimesheetTask(SQLModel):
    id: int
    title: str
    project_id: int


class TimesheetRead(TimesheetBase):
    id: int
    week_start: date
    week_end: date
    created_at: datetime
    updated_at: datetime
    user: TimesheetUser
    task: Optional[TimesheetTask] = None


# Summary schemas for weekly reports
class WeeklyTimesheetSummary(SQLModel):
    user_id: int
    full_name: str
    job_title: str
    department: Optional[str]
    week_start: date
    week_end: date
    total_working_hours: float = 0.0
    total_task_hours: float = 0.0
    daily_entries: List["DailyTimesheetEntry"] = []


class DailyTimesheetEntry(SQLModel):
    date: date
    working_hours: float = 0.0
    task_hours: float = 0.0
    status: str


# Bulk operations
class TimesheetBulkCreate(SQLModel):
    user_id: int
    week_start: date
    daily_entries: List["DailyTimesheetCreate"]


class DailyTimesheetCreate(SQLModel):
    date: date
    working_hours: float = 8.0  # Default 8 hours
    task_hours: float = 0.0
    description: Optional[str] = None



# schemas/timesheet_schema.py - Add these new schemas

class UserTaskDay(BaseModel):
    """Represents a task for a specific day in the timesheet"""
    task_id: int
    task_title: str
    task_description: Optional[str] = None
    project_id: int
    project_name: Optional[str] = None
    status: str
    priority: str
    due_date: Optional[datetime] = None
    estimated_hours: float = 0.0
    logged_hours: float = 0.0
    is_completed: bool = False

    model_config = ConfigDict(from_attributes=True)


class UserTaskWeekResponse(BaseModel):
    """Response model for user tasks in a week"""
    user_id: int
    user_name: str
    week_start: date
    week_end: date
    daily_tasks: Dict[date, List[UserTaskDay]]  # Tasks grouped by date
    daily_totals: Dict[date, float]  # Total hours per day
    week_total_hours: float
    total_tasks: int

    model_config = ConfigDict(from_attributes=True)