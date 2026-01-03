"""
Leave Management Database Models for Multi-Tenant System
"""

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime, UTC, date as date_type
from sqlalchemy import Column, Integer, String, DateTime, Date, Text, Boolean, ForeignKey, Enum, UniqueConstraint, CheckConstraint, Index
from .models import Organization
from .models import User
import enum


class LeaveTypeEnum(str, enum.Enum):
    ANNUAL = "Annual Leave"
    SICK = "Sick Leave"
    PERSONAL = "Personal Leave"
    UNPAID = "Unpaid Leave"


class LeaveTypeCode(str, enum.Enum):
    ANNUAL = "ANNUAL"
    SICK = "SICK"
    PERSONAL = "PERSONAL"
    UNPAID = "UNPAID"


class LeaveType(SQLModel, table=True):
    """Leave type definition - ISOLATED per organization"""
    __tablename__ = "leave_types"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String(100), nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    max_days: int = Field(default=0, ge=0)
    is_paid: bool = Field(default=True)
    color: Optional[str] = Field(default="#3B82F6", sa_column=Column(String(20)))
    icon: Optional[str] = Field(default="FiCalendar", sa_column=Column(String(50)))
    organization_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC))
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    )
    
    # Relationships - ISOLATED to organization
    leave_requests: List["LeaveRequest"] = Relationship(back_populates="leave_type")
    leave_balances: List["LeaveBalance"] = Relationship(back_populates="leave_type")
    organization: Optional["Organization"] = Relationship(back_populates="leave_types")
    
    # Composite unique constraint - name must be unique per organization
    __table_args__ = (
        UniqueConstraint("name", "organization_id", name="uq_leave_type_name_org"),
        CheckConstraint("max_days >= 0", name="check_max_days_non_negative"),
        Index("ix_leave_types_organization_id", "organization_id"),
    )


class LeaveRequest(SQLModel, table=True):
    """Leave request model - ISOLATED per organization"""
    __tablename__ = "leave_requests"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    )
    organization_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    )
    leave_type_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False)
    )
    start_date: date_type = Field(sa_column=Column(Date, nullable=False))
    end_date: date_type = Field(sa_column=Column(Date, nullable=False))
    duration_days: int = Field(nullable=False, ge=0)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    emergency_contact: Optional[str] = Field(default=None, sa_column=Column(String(50)))
    handover_person_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    )
    handover_notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    status: str = Field(
        default="pending",
        sa_column=Column(Enum("pending", "approved", "rejected", "cancelled", name="leave_status"))
    )
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC))
    )
    admin_comments: Optional[str] = Field(default=None, sa_column=Column(Text))
    approved_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    )
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime))
    year: int = Field(sa_column=Column(Integer, nullable=False))
    month: int = Field(sa_column=Column(Integer, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC))
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    )
    
    # Relationships - All isolated to organization
    user: "User" = Relationship(
        back_populates="leave_requests",
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.user_id]"}
    )
    organization: "Organization" = Relationship(back_populates="leave_requests")
    leave_type: LeaveType = Relationship(back_populates="leave_requests")
    handover_person: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.handover_person_id]"},
        back_populates="handover_leave_requests"
    )
    approver: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.approved_by]"},
        back_populates="approved_leave_requests"
    )
    
    __table_args__ = (
        CheckConstraint("duration_days >= 0", name="check_duration_non_negative"),
        CheckConstraint("end_date >= start_date", name="check_end_date_after_start"),
        Index("ix_leave_requests_organization_id", "organization_id"),
        Index("ix_leave_requests_user_id", "user_id"),
        Index("ix_leave_requests_leave_type_id", "leave_type_id"),
        Index("ix_leave_requests_status", "status"),
        Index("ix_leave_requests_start_date_end_date", "start_date", "end_date"),
    )


class LeaveBalance(SQLModel, table=True):
    """Leave balance per user per type - ISOLATED per organization"""
    __tablename__ = "leave_balances"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    )
    organization_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False)
    )
    leave_type_id: int = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False)
    )
    total_days: int = Field(default=0, ge=0)
    used_days: int = Field(default=0, ge=0)
    remaining_days: int = Field(default=0, ge=0)
    fiscal_year: int = Field(nullable=False)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    last_updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    )
    last_updated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC))
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    )
    
    # Relationships - All isolated to organization
    user: "User" = Relationship(
        back_populates="leave_balances",
        sa_relationship_kwargs={"foreign_keys": "[LeaveBalance.user_id]"}
    )
    organization: "Organization" = Relationship(back_populates="leave_balances")
    leave_type: "LeaveType" = Relationship(back_populates="leave_balances")
    updated_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[LeaveBalance.last_updated_by]"}
    )
    
    # Composite unique constraint - ensures balance is unique per user, leave type, fiscal year AND organization
    __table_args__ = (
        UniqueConstraint("user_id", "leave_type_id", "fiscal_year", "organization_id", 
                        name="uq_leave_balance_user_type_year_org"),
        CheckConstraint("total_days >= 0", name="check_total_days_non_negative"),
        CheckConstraint("used_days >= 0", name="check_used_days_non_negative"),
        CheckConstraint("remaining_days >= 0", name="check_remaining_days_non_negative"),
        CheckConstraint("used_days <= total_days", name="check_used_less_than_total"),
        CheckConstraint("total_days >= used_days", name="check_total_gte_used"),
        Index("ix_leave_balances_organization_id", "organization_id"),
        Index("ix_leave_balances_user_id", "user_id"),
        Index("ix_leave_balances_leave_type_id", "leave_type_id"),
        Index("ix_leave_balances_fiscal_year", "fiscal_year"),
        {"sqlite_autoincrement": True}
    )