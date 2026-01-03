from __future__ import annotations

# schemas/attendance_schema.py
from pydantic import BaseModel, Field, ConfigDict, validator
from typing import Optional, List
from datetime import datetime, date as date_type, time
from enum import Enum


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LEAVE = "leave"
    HALF_DAY = "half_day"
    LATE = "late"


class BreakType(str, Enum):
    LUNCH = "lunch"
    TEA = "tea"
    BREAK = "break"
    NAMAZ = "namaz"
    PERSONAL = "personal"


class WorkLocation(str, Enum):
    OFFICE = "Office"
    REMOTE = "Remote"
    CLIENT_SITE = "Client Site"
    FIELD_WORK = "Field Work"


# ============================================================
# ✅ Create/Update Schemas
# ============================================================
class BreakSchema(BaseModel):
    type: BreakType
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    duration: Optional[str] = None


class AttendanceCreate(BaseModel):
    # date: date_type = Field(default_factory=date_type.today)
    date: date_type = Field(default_factory=lambda: date_type.today())
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    location: Optional[WorkLocation] = None
    status: AttendanceStatus = Field(default=AttendanceStatus.PRESENT)
    breaks: Optional[List[BreakSchema]] = Field(default_factory=list)
    notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class AttendanceUpdate(BaseModel):
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    location: Optional[WorkLocation] = None
    status: Optional[AttendanceStatus] = None
    breaks: Optional[List[BreakSchema]] = None
    notes: Optional[str] = None
    is_late: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)


class ManualAttendanceCreate(BaseModel):
    user_id: int
    date: date_type
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    location: Optional[WorkLocation] = None
    status: AttendanceStatus
    notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# ✅ Read Schemas
# ============================================================
class AttendanceRead(BaseModel):
    id: int
    user_id: int
    date: date_type
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    total_hours: Optional[str] = None
    location: Optional[str] = None  # Changed to str (was WorkLocation enum)
    status: str  # Changed to str (was AttendanceStatus enum)
    is_late: bool = False
    overtime: Optional[str] = None
    breaks: Optional[List[BreakSchema]] = Field(default_factory=list)
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # Employee info
    employee_name: Optional[str] = None
    employee_role: Optional[str] = None
    employee_avatar: Optional[str] = None
    
    # Computed fields
    productive_hours: Optional[str] = None
    break_time: Optional[str] = None
    total_minutes: Optional[int] = None
    productive_minutes: Optional[int] = None
    overtime_minutes: Optional[int] = None

    # Geolocation
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class AttendanceStats(BaseModel):
    total_employees: int
    present_today: int
    on_leave: int
    average_hours: float
    late_arrivals: int
    remote_workers: int = 0
    office_workers: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class AttendanceSummary(BaseModel):
    user_id: int
    employee_name: str
    employee_role: Optional[str] = None
    total_days: int
    present_days: int
    absent_days: int
    leave_days: int
    average_hours: float
    late_count: int
    last_check_in: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class AttendanceFilter(BaseModel):
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    user_id: Optional[int] = None
    status: Optional[AttendanceStatus] = None
    location: Optional[WorkLocation] = None
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# ✅ Check In/Out Schemas
# ============================================================
class CheckInRequest(BaseModel):
    location: str  # Accept plain string, not enum (more flexible for frontend)
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class CheckOutRequest(BaseModel):
    notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class BreakRequest(BaseModel):
    break_type: str  # Accept plain string (more flexible for frontend)
    notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class TodayStatus(BaseModel):
    is_checked_in: bool
    check_in_time: Optional[str] = None  # HH:MM format
    check_out_time: Optional[str] = None  # HH:MM format
    total_hours: Optional[str] = None  # HH:MM format
    break_time: Optional[str] = None  # HH:MM format
    productive_hours: Optional[str] = None  # HH:MM format
    current_location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    active_break: Optional[dict] = None  # Simplified to dict
    today_breaks: Optional[List] = None  # List of break history
    current_break: Optional[dict] = None  # For active break details
    
    model_config = ConfigDict(from_attributes=True)





class AttendanceTrackingResponse(BaseModel):
    """Response model for attendance tracking endpoint"""
    user_id: int
    employee_name: str
    employee_email: str
    employee_role: str
    employee_avatar: Optional[str] = None
    date: date_type
    check_in_display: str
    check_out_display: str
    break_display: str
    total_hours: Optional[str] = None
    productive_hours: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    status: str
    is_late: bool
    weekly_hours: Optional[str] = None
    weekly_attendance: Optional[str] = None
    
    # Metadata
    pagination: Optional[dict] = None
    summary: Optional[dict] = None
    
    model_config = ConfigDict(from_attributes=True)


class EmployeeAttendanceHistory(BaseModel):
    """Response model for employee attendance history"""
    employee: dict
    date_range: dict
    summary: dict
    monthly_stats: dict
    attendance_records: List[dict]
    
    model_config = ConfigDict(from_attributes=True)