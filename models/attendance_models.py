# models/attendance_models.py
from datetime import datetime, UTC, date as date_type, time, timedelta
from typing import Optional, List, Dict, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column, String, JSON
from sqlalchemy import event
from sqlalchemy.orm import relationship
import json
from enum import Enum

if TYPE_CHECKING:
    from .models import User, Organization


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
# ATTENDANCE MODEL
# ============================================================
class Attendance(SQLModel, table=True):
    __tablename__ = "attendance"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", nullable=False, index=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    
    # Date
    date: date_type = Field(default_factory=lambda: date_type.today(), index=True, nullable=False)
    
    # Check in/out times
    check_in: Optional[time] = None
    check_out: Optional[time] = None
    
    # Daily calculated fields
    total_hours: Optional[str] = Field(default=None, max_length=10)  # HH:MM format
    productive_hours: Optional[str] = Field(default=None, max_length=10)  # HH:MM format
    break_time: Optional[str] = Field(default=None, max_length=10)  # HH:MM format
    overtime: Optional[str] = Field(default=None, max_length=10)  # HH:MM format
    
    # Aggregation helpers (for faster queries)
    total_minutes: Optional[int] = Field(default=0, index=True)  # Total minutes worked
    productive_minutes: Optional[int] = Field(default=0, index=True)  # Productive minutes (total - breaks)
    overtime_minutes: Optional[int] = Field(default=0, index=True)  # Overtime minutes
    
    # Date helpers for aggregation
    year: Optional[int] = Field(default=None, index=True)  # e.g., 2024
    month: Optional[int] = Field(default=None, index=True)  # 1-12
    week_number: Optional[int] = Field(default=None, index=True)  # ISO week number
    day_of_week: Optional[int] = Field(default=None, index=True)  # Monday=0, Sunday=6
    
    # Location
    location: Optional[str] = Field(default=None, max_length=50)
    
    # Status
    status: str = Field(default=AttendanceStatus.PRESENT.value, max_length=20, index=True)
    is_late: bool = Field(default=False, index=True)
    
    # Breaks (stored as JSON)
    breaks_data: Optional[str] = Field(default=None, sa_column=Column(JSON))
    
    # Geolocation
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    
    # Notes
    notes: Optional[str] = Field(default=None, max_length=500)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # Relationships
    user: "User" = Relationship()
    organization: "Organization" = Relationship()
    
    @property
    def breaks_list(self) -> List[Dict]:
        """Parse breaks JSON to list"""
        if not self.breaks_data:
            return []
        try:
            return json.loads(self.breaks_data) if isinstance(self.breaks_data, str) else self.breaks_data
        except:
            return []
    
    @breaks_list.setter
    def breaks_list(self, value: List[Dict]):
        """Set breaks as JSON string"""
        self.breaks_data = json.dumps(value) if value else None
    
    def calculate_hours(self, db_session=None):
        """
        Calculate all hours for this attendance record.
        Uses server timestamps as single source of truth.
        
        Args:
            db_session: Optional SQLModel session to query BreakHistory
        """
        # Set date helpers (even if only check_in exists)
        self.year = self.date.year
        self.month = self.date.month
        self.week_number = self.date.isocalendar()[1]
        self.day_of_week = self.date.weekday()  # Monday=0, Sunday=6
        
        # If no check-in, reset all to zero
        if not self.check_in:
            self._reset_hours()
            return
        
        # Handle check-in and check-out times with proper cross-midnight support
        if self.check_out:
            # Both check-in and check-out exist - handle cross-midnight scenarios
            check_in_dt = datetime.combine(self.date, self.check_in).replace(tzinfo=UTC)
            
            # Check if check-out time is earlier than check-in (indicates cross-midnight)
            if self.check_out < self.check_in:
                # Cross-midnight scenario: check-out is on the next day
                check_out_dt = datetime.combine(self.date + timedelta(days=1), self.check_out).replace(tzinfo=UTC)
            else:
                # Same-day scenario
                check_out_dt = datetime.combine(self.date, self.check_out).replace(tzinfo=UTC)
        else:
            # Only check-in exists, calculate from check-in to current time
            check_in_dt = datetime.combine(self.date, self.check_in).replace(tzinfo=UTC)
            check_out_dt = datetime.now(UTC)  # Use current time for live calculation
        
        # Calculate time difference
        delta = check_out_dt - check_in_dt
        total_minutes = int(delta.total_seconds() / 60)
        
        # Ensure we never have negative minutes (safety check)
        if total_minutes < 0:
            total_minutes = 0
        
        # Calculate break minutes from BreakHistory table (server-side truth)
        # If db_session is provided, query from BreakHistory
        # Otherwise fall back to breaks_list (for backward compatibility)
        if db_session and self.id:
            break_minutes = self._calculate_break_minutes_from_db(db_session)
        else:
            break_minutes = self._calculate_break_minutes()
        
        # Calculate productive minutes (total - breaks)
        productive_minutes = max(0, total_minutes - break_minutes)
        
        # Calculate overtime (anything over 8 hours = 480 minutes)
        standard_minutes = 8 * 60
        overtime_minutes = max(0, productive_minutes - standard_minutes)
        
        # Update minute fields
        self.total_minutes = total_minutes
        self.productive_minutes = productive_minutes
        self.overtime_minutes = overtime_minutes
        
        # Update formatted fields
        self.total_hours = self._minutes_to_hhmm(total_minutes)
        self.break_time = self._minutes_to_hhmm(break_minutes)
        self.productive_hours = self._minutes_to_hhmm(productive_minutes)
        self.overtime = self._minutes_to_hhmm(overtime_minutes)
        
        # Check if late
        self.is_late = self.check_if_late()
    
    def _reset_hours(self):
        """Reset all hour fields to zero"""
        self.total_minutes = 0
        self.productive_minutes = 0
        self.overtime_minutes = 0
        
        self.total_hours = "00:00"
        self.break_time = "00:00"
        self.productive_hours = "00:00"
        self.overtime = "00:00"
    
    def _calculate_break_minutes_from_db(self, db_session) -> int:
        """
        Calculate total break minutes from BreakHistory table (server-side truth).
        
        Args:
            db_session: SQLModel database session
            
        Returns:
            Total break minutes
        """
        from sqlmodel import select
        
        # Import here to avoid circular dependency
        # Query all completed breaks for today's attendance
        today_start = datetime.combine(self.date, datetime.min.time()).replace(tzinfo=UTC)
        today_end = datetime.combine(self.date, datetime.max.time()).replace(tzinfo=UTC)
        
        breaks = db_session.exec(
            select(BreakHistory).where(
                BreakHistory.user_id == self.user_id,
                BreakHistory.organization_id == self.organization_id,
                BreakHistory.start_time >= today_start,
                BreakHistory.start_time <= today_end,
                BreakHistory.end_time.is_not(None)  # Only completed breaks
            )
        ).all()
        
        total_break_minutes = 0
        for break_item in breaks:
            if break_item.duration and ':' in break_item.duration:
                try:
                    hours, minutes = break_item.duration.split(':')
                    total_break_minutes += int(hours) * 60 + int(minutes)
                except (ValueError, IndexError):
                    # Skip invalid duration format
                    continue
        
        return total_break_minutes
    
    def _calculate_break_minutes(self) -> int:
        """
        Calculate total break minutes from breaks_list (fallback method).
        This is used when db_session is not available.
        """
        break_minutes = 0
        for break_item in self.breaks_list:
            if break_item.get('duration'):
                # Parse duration string like "1:30"
                if ':' in break_item['duration']:
                    try:
                        hours, minutes = break_item['duration'].split(':')
                        break_minutes += int(hours) * 60 + int(minutes)
                    except (ValueError, IndexError):
                        # Skip invalid format
                        continue
        return break_minutes
    
    def _minutes_to_hhmm(self, minutes: int) -> str:
        """Convert minutes to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"
    
    def check_if_late(self, expected_time: time = time(9, 0)) -> bool:
        """Check if employee was late"""
        if not self.check_in:
            return False
        
        # Create timezone-aware datetime objects for accurate comparison
        check_in_time = datetime.combine(self.date, self.check_in).replace(tzinfo=UTC)
        expected_datetime = datetime.combine(self.date, expected_time).replace(tzinfo=UTC)
        
        # 15 minutes grace period
        grace_period = timedelta(minutes=15)
        return check_in_time > (expected_datetime + grace_period)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary with all fields"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "date": self.date.isoformat() if self.date else None,
            "check_in": self.check_in.strftime("%H:%M") if self.check_in else None,
            "check_out": self.check_out.strftime("%H:%M") if self.check_out else None,
            "total_hours": self.total_hours,
            "productive_hours": self.productive_hours,
            "break_time": self.break_time,
            "overtime": self.overtime,
            "location": self.location,
            "status": self.status,
            "is_late": self.is_late,
            "breaks": self.breaks_list,
            "year": self.year,
            "month": self.month,
            "week_number": self.week_number,
            "day_of_week": self.day_of_week
        }



# Add this class in the same file (attendance_models.py)
class TimeAggregator:
    """Utility class to aggregate time data"""
    
    @staticmethod
    def calculate_daily_hours(attendance_list: List['Attendance']) -> Dict:
        """Calculate daily hours from list of attendance records"""
        total_minutes = sum(a.total_minutes or 0 for a in attendance_list)
        productive_minutes = sum(a.productive_minutes or 0 for a in attendance_list)
        break_minutes = sum(a._calculate_break_minutes() for a in attendance_list)
        overtime_minutes = sum(a.overtime_minutes or 0 for a in attendance_list)
        
        return {
            "total_hours": TimeAggregator._minutes_to_hhmm(total_minutes),
            "productive_hours": TimeAggregator._minutes_to_hhmm(productive_minutes),
            "break_time": TimeAggregator._minutes_to_hhmm(break_minutes),
            "overtime": TimeAggregator._minutes_to_hhmm(overtime_minutes),
            "days_count": len(attendance_list)
        }
    
    @staticmethod
    def calculate_weekly_hours(attendance_dict: Dict[int, List['Attendance']]) -> Dict[int, Dict]:
        """Calculate weekly hours from dict of {week_number: [attendance]}"""
        result = {}
        for week_num, attendances in attendance_dict.items():
            daily_result = TimeAggregator.calculate_daily_hours(attendances)
            result[week_num] = daily_result
        return result
    
    @staticmethod
    def calculate_monthly_hours(attendance_dict: Dict[str, List['Attendance']]) -> Dict[str, Dict]:
        """Calculate monthly hours from dict of {year-month: [attendance]}"""
        result = {}
        for month_key, attendances in attendance_dict.items():
            daily_result = TimeAggregator.calculate_daily_hours(attendances)
            result[month_key] = daily_result
        return result
    
    @staticmethod
    def calculate_yearly_hours(attendance_dict: Dict[int, List['Attendance']]) -> Dict[int, Dict]:
        """Calculate yearly hours from dict of {year: [attendance]}"""
        result = {}
        for year, attendances in attendance_dict.items():
            daily_result = TimeAggregator.calculate_daily_hours(attendances)
            result[year] = daily_result
        return result
    
    @staticmethod
    def _minutes_to_hhmm(minutes: int) -> str:
        """Convert minutes to HH:MM format"""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"


# ============================================================
# ACTIVE SESSION MODEL (for tracking current check-in/break)
# ============================================================
class ActiveSession(SQLModel, table=True):
    __tablename__ = "active_session"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, nullable=False, index=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    
    # Check in details
    is_checked_in: bool = Field(default=False)
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    check_in_location: Optional[str] = Field(default=None, max_length=50)
    
    # Break details
    is_on_break: bool = Field(default=False)
    break_start_time: Optional[datetime] = None
    break_type: Optional[str] = Field(default=None, max_length=20)
    break_notes: Optional[str] = Field(default=None, max_length=500)
    
    # Geolocation
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # Relationships
    user: "User" = Relationship()


# ============================================================
# BREAK HISTORY MODEL
# ============================================================
class BreakHistory(SQLModel, table=True):
    __tablename__ = "break_history"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", nullable=False, index=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    attendance_id: Optional[int] = Field(foreign_key="attendance.id", index=True)
    
    break_type: str = Field(max_length=20)
    start_time: datetime = Field(nullable=False)
    end_time: Optional[datetime] = None
    duration: Optional[str] = Field(default=None, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=500)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # Relationships
    user: "User" = Relationship()
    attendance: Optional["Attendance"] = Relationship()


# ============================================================
# EVENT LISTENERS
# ============================================================
@event.listens_for(Attendance, 'before_update')
def update_timestamp(mapper, connection, target):
    target.updated_at = datetime.now(UTC)