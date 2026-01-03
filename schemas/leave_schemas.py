"""
Leave Management Schemas
Pydantic models for request/response validation
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date as date_type
from pydantic import BaseModel, Field, validator, ConfigDict
from decimal import Decimal


class LeaveTypeSchema(BaseModel):
    """Leave type schema"""
    id: int
    name: str
    description: Optional[str] = None
    max_days: int
    is_paid: bool
    color: Optional[str] = "#3B82F6"
    icon: Optional[str] = "FiCalendar"
    organization_id: int
    
    class Config:
        from_attributes = True


class LeaveBalanceSchema(BaseModel):
    """Leave balance schema"""
    id: int
    user_id: int
    leave_type_id: int
    total_days: int
    used_days: int
    remaining_days: int
    fiscal_year: int
    leave_type: LeaveTypeSchema
    organization_id: int
    
    class Config:
        from_attributes = True


class LeaveRequestCreate(BaseModel):
    """Schema for creating a leave request"""
    leave_type_id: int
    start_date: date_type
    end_date: date_type
    reason: str
    emergency_contact: Optional[str] = None
    handover_person_id: Optional[int] = None
    handover_notes: Optional[str] = None
    
    @validator('end_date')
    def validate_dates(cls, end_date, values):
        if 'start_date' in values and end_date < values['start_date']:
            raise ValueError('end_date must be after or equal to start_date')
        return end_date


class LeaveRequestUpdate(BaseModel):
    """Schema for updating a leave request (admin only)"""
    status: Optional[str] = None
    admin_comments: Optional[str] = None


class LeaveRequestSchema(BaseModel):
    """Leave request schema with full details"""
    id: int
    user_id: int
    organization_id: int
    employee_name: str
    employee_role: str
    leave_type_id: int
    leave_type_name: str
    start_date: date_type
    end_date: date_type
    duration_days: int
    reason: str
    emergency_contact: Optional[str] = None
    handover_person_id: Optional[int] = None
    handover_person_name: Optional[str] = None
    handover_notes: Optional[str] = None
    status: str
    submitted_at: datetime
    admin_comments: Optional[str] = None
    approved_by: Optional[int] = None
    approved_by_name: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LeaveStatsSchema(BaseModel):
    """Leave statistics"""
    total_requests: int
    pending: int
    approved: int
    rejected: int
    this_month: int
    average_duration: float
    leave_type_distribution: Dict[str, int]
    organization_id: int


class EmployeeLeaveBalanceSummary(BaseModel):
    """Summary of employee leave balance"""
    employee_id: int
    employee_name: str
    email: str
    role: str
    department: Optional[str] = None
    organization_id: int
    leave_balances: List[LeaveBalanceSchema]
    total_remaining: int
    total_used: int
    last_leave_request: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class LeaveBalanceUpdateRequest(BaseModel):
    """Schema for updating leave balance (admin only)"""
    leave_type_id: int
    action: str = Field(..., description="add, subtract, or set")
    days: int = Field(..., ge=0, description="Number of days")
    notes: Optional[str] = None
    effective_date: Optional[date_type] = None
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['add', 'subtract', 'set']:
            raise ValueError('Action must be "add", "subtract", or "set"')
        return v


class BulkLeaveBalanceUpdate(BaseModel):
    """Schema for bulk leave balance updates"""
    employee_ids: List[int]
    leave_type_id: int
    action: str = Field(..., description="add, subtract, or set")
    days: int = Field(..., ge=0, description="Number of days")
    notes: Optional[str] = None


class LeaveOverviewResponse(BaseModel):
    """Response for leave overview"""
    total_employees: int
    leave_types: List[Dict[str, Any]]
    department_summary: Dict[str, Any]
    low_balance_alerts: List[Dict[str, Any]]
    organization_id: int


# NEW: Schema for unpaid leave validation
class UnpaidLeaveValidation(BaseModel):
    """Validation for unpaid leave requests"""
    has_sufficient_paid_balance: bool
    total_paid_remaining: int
    unpaid_balance: Optional[LeaveBalanceSchema] = None
    can_apply_unpaid: bool
    message: str


# NEW: Schema for leave overlap check
class LeaveOverlapCheck(BaseModel):
    """Check for overlapping leave requests"""
    has_overlap: bool
    overlapping_requests: List[LeaveRequestSchema] = []
    message: str


# NEW: Schema for leave application validation
class LeaveApplicationValidation(BaseModel):
    """Validation result for leave application"""
    is_valid: bool
    has_sufficient_balance: bool
    has_overlap: bool
    unpaid_validation: Optional[UnpaidLeaveValidation] = None
    message: str
    errors: List[str] = []
    warnings: List[str] = []
    available_balance: Optional[float] = None
    requested_days: Optional[int] = None


