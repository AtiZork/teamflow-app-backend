# Create a new file: schemas/hours_schema.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict
from datetime import date, datetime
from enum import Enum


class HoursPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class EmployeeHours(BaseModel):
    employee_id: int
    employee_name: str
    employee_role: Optional[str] = None
    total_hours: str  # Format: "HH:MM"
    productive_hours: str  # Format: "HH:MM"
    break_time: str  # Format: "HH:MM"
    overtime: str  # Format: "HH:MM"
    working_days: int
    average_daily_hours: str  # Format: "HH:MM"
    
    model_config = ConfigDict(from_attributes=True)


class DailyHours(BaseModel):
    date: date
    day_name: str
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    total_hours: str
    productive_hours: str
    break_time: str
    overtime: str
    status: str
    location: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class WeeklySummary(BaseModel):
    week_number: int
    week_start: date
    week_end: date
    total_hours: str
    productive_hours: str
    average_daily_hours: str
    overtime_total: str
    working_days: int
    days: List[DailyHours]
    
    model_config = ConfigDict(from_attributes=True)


class MonthlySummary(BaseModel):
    month_year: str  # Format: "YYYY-MM"
    month_name: str
    total_hours: str
    productive_hours: str
    average_daily_hours: str
    overtime_total: str
    working_days: int
    absent_days: int
    leave_days: int
    late_days: int
    weekly_breakdown: List[WeeklySummary]
    
    model_config = ConfigDict(from_attributes=True)


class EmployeeHoursSummary(BaseModel):
    employee_id: int
    employee_name: str
    today_hours: Optional[DailyHours] = None
    current_week: Optional[WeeklySummary] = None
    current_month: Optional[MonthlySummary] = None
    year_to_date: Dict[str, str]  # Total hours, productive hours, etc.
    
    model_config = ConfigDict(from_attributes=True)


class HoursReportRequest(BaseModel):
    period: HoursPeriod
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    employee_ids: Optional[List[int]] = None
    department_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)