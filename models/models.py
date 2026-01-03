# # teamflow_backend/models.py 
# teamflow_backend/models.py 
from typing import Optional, List, Dict
from datetime import datetime, UTC, timedelta
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint, Column, String, ForeignKey
from sqlalchemy.orm import relationship
from pydantic import EmailStr
from typing import TYPE_CHECKING
import json

if TYPE_CHECKING:
    from .leave_models import LeaveRequest, LeaveBalance, LeaveType


# ============================================================
# ENUMS
# ============================================================
class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MEMBER = "member"


class PlanName(str, Enum):
    FREE = "Free"
    PRO = "Pro"
    TEAM = "Team"


class PaymentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    PENDING = "pending"
    FAILED = "failed"


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class TimesheetStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


# ============================================================
# LINK MODEL
# ============================================================
class TaskMemberLink(SQLModel, table=True):
    __tablename__ = "task_member_link"
    task_id: int = Field(foreign_key="task.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)


# ============================================================
# TIMESHEET MODEL
# ============================================================
class Timesheet(SQLModel, table=True):
    __tablename__ = "timesheet"

    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Foreign keys
    user_id: int = Field(foreign_key="user.id", nullable=False, index=True)
    task_id: Optional[int] = Field(default=None, foreign_key="task.id", index=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    
    # Time tracking - use datetime for all date fields
    date: datetime = Field(index=True, nullable=False)
    working_hours: float = Field(default=0.0, ge=0.0, le=24.0)
    task_hours: float = Field(default=0.0, ge=0.0, le=24.0)
    
    # Week information for efficient querying
    week_start: datetime = Field(index=True, nullable=False)
    week_end: datetime = Field(index=True, nullable=False)
    
    # Status and metadata
    status: str = Field(default=TimesheetStatus.DRAFT.value, max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    user: "User" = Relationship(back_populates="timesheets")
    task: Optional["Task"] = Relationship(back_populates="timesheets")
    organization: Optional["Organization"] = Relationship(back_populates="timesheets")

    def calculate_week_dates(self):
        """Calculate week start (Monday) and end (Sunday) for the given date"""
        # Extract date part for calculation
        date_obj = self.date.date() if isinstance(self.date, datetime) else self.date
        weekday = date_obj.weekday()  # Monday is 0, Sunday is 6
        week_start_date = date_obj - timedelta(days=weekday)
        week_end_date = week_start_date + timedelta(days=6)  # Sunday
        
        # Convert back to datetime
        self.week_start = datetime.combine(week_start_date, datetime.min.time())
        self.week_end = datetime.combine(week_end_date, datetime.min.time())

    @property
    def is_future_date(self) -> bool:
        """Check if this timesheet entry is for a future date"""
        from datetime import datetime
        return self.date.date() > datetime.now(UTC).date() if isinstance(self.date, datetime) else self.date > datetime.now(UTC).date()


# ============================================================
# ORGANIZATION (tenant)
# ============================================================
class Organization(SQLModel, table=True):
    __tablename__ = "organization"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    slug: Optional[str] = Field(default=None, max_length=50, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    super_admin_id: Optional[int] = Field(foreign_key="user.id", nullable=True, index=True)

    # ✅ This field links to the currently active payment
    current_payment_id: Optional[int] = Field(default=None, foreign_key="payment.id", index=True)

    # ✅ Relationships
    users: List["User"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"foreign_keys": "User.organization_id"}
    )
    projects: List["Project"] = Relationship(back_populates="organization")
    tasks: List["Task"] = Relationship(back_populates="organization")
    invitations: List["Invitation"] = Relationship(back_populates="organization")
    payments: List["Payment"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"foreign_keys": "[Payment.organization_id]"}
    )
    invoices: List["Invoice"] = Relationship(back_populates="organization")
    webhook_events: List["WebhookEvent"] = Relationship(back_populates="organization")
    timesheets: List["Timesheet"] = Relationship(back_populates="organization")
    
    # ✅ LEAVE MANAGEMENT RELATIONSHIPS (ADD THESE)
    leave_requests: List["LeaveRequest"] = Relationship(back_populates="organization")
    leave_balances: List["LeaveBalance"] = Relationship(back_populates="organization")
    leave_types: List["LeaveType"] = Relationship(back_populates="organization")

    current_payment: Optional["Payment"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Organization.current_payment_id]"}
    )

    super_admin: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Organization.super_admin_id]"}
    )


# ============================================================
# USER
# ============================================================
class User(SQLModel, table=True):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_org_email"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str = Field(max_length=100)
    email: EmailStr = Field(index=True, max_length=100, nullable=False)
    username: Optional[str] = Field(default=None, max_length=50, index=True)
    password_hash: str = Field(nullable=False)

    # Role + public marker
    role: str = Field(default=UserRole.MEMBER.value, max_length=20, index=True)
    is_public_admin: bool = Field(default=False, index=True, description="True for public signups that are tenant bootstrappers")

    is_active: bool = Field(default=True)
    is_invited: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_joined: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Profile
    department: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture: Optional[str] = None
    phone_number: Optional[str] = None
    time_zone: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None

    # Relations
    organization_id: int = Field(foreign_key="organization.id", index=True)
    organization: Optional["Organization"] = Relationship(
        back_populates="users",
        sa_relationship_kwargs={"foreign_keys": "[User.organization_id]"}
    )

    # Relationships
    projects: List["Project"] = Relationship(back_populates="creator")
    tasks: List["Task"] = Relationship(back_populates="members", link_model=TaskMemberLink)
    sent_invitations: List["Invitation"] = Relationship(back_populates="sent_by")
    comments: List["TaskComment"] = Relationship(back_populates="user")

    # ✅ Cascade delete work logs when user is deleted
    work_logs: List["TaskWorkLog"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    payments: List["Payment"] = Relationship(back_populates="user")
    timesheets: List["Timesheet"] = Relationship(back_populates="user")

    # ✅ LEAVE MANAGEMENT RELATIONSHIPS (ADD THESE - ONLY ONCE!)
    leave_requests: List["LeaveRequest"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.user_id]"}
    )
    leave_balances: List["LeaveBalance"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[LeaveBalance.user_id]"}
    )
    handover_leave_requests: List["LeaveRequest"] = Relationship(
        back_populates="handover_person",
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.handover_person_id]"}
    )
    approved_leave_requests: List["LeaveRequest"] = Relationship(
        back_populates="approver",
        sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.approved_by]"}
    )

    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN.value and self.is_public_admin is True

# ... REST OF THE FILE (Project, Task, etc. remains unchanged) ...





# from typing import Optional, List, Dict
# from datetime import datetime, UTC, timedelta
# from enum import Enum
# from sqlmodel import SQLModel, Field, Relationship
# from sqlalchemy import UniqueConstraint, Column, String, ForeignKey
# from sqlalchemy.orm import relationship
# from pydantic import EmailStr
# from typing import TYPE_CHECKING
# import json

# if TYPE_CHECKING:
#     from .leave_models import LeaveRequest, LeaveBalance, LeaveType


# # ============================================================
# # ENUMS
# # ============================================================
# class UserRole(str, Enum):
#     SUPER_ADMIN = "super_admin"
#     ADMIN = "admin"
#     MEMBER = "member"


# class PlanName(str, Enum):
#     FREE = "Free"
#     PRO = "Pro"
#     TEAM = "Team"


# class PaymentStatus(str, Enum):
#     ACTIVE = "active"
#     INACTIVE = "inactive"
#     CANCELLED = "cancelled"
#     EXPIRED = "expired"
#     PAST_DUE = "past_due"
#     TRIALING = "trialing"
#     PENDING = "pending"
#     FAILED = "failed"


# class BillingCycle(str, Enum):
#     MONTHLY = "monthly"
#     YEARLY = "yearly"


# class InvitationStatus(str, Enum):
#     PENDING = "pending"
#     ACCEPTED = "accepted"
#     EXPIRED = "expired"


# class TimesheetStatus(str, Enum):
#     DRAFT = "draft"
#     SUBMITTED = "submitted"
#     APPROVED = "approved"
#     REJECTED = "rejected"


# # ============================================================
# # LINK MODEL
# # ============================================================
# class TaskMemberLink(SQLModel, table=True):
#     __tablename__ = "task_member_link"
#     task_id: int = Field(foreign_key="task.id", primary_key=True)
#     user_id: int = Field(foreign_key="user.id", primary_key=True)
#     organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)


# # ============================================================
# # TIMESHEET MODEL
# # ============================================================
# class Timesheet(SQLModel, table=True):
#     __tablename__ = "timesheet"

#     id: Optional[int] = Field(default=None, primary_key=True)
    
#     # Foreign keys
#     user_id: int = Field(foreign_key="user.id", nullable=False, index=True)
#     task_id: Optional[int] = Field(default=None, foreign_key="task.id", index=True)
#     organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    
#     # Time tracking - use datetime for all date fields
#     date: datetime = Field(index=True, nullable=False)
#     working_hours: float = Field(default=0.0, ge=0.0, le=24.0)
#     task_hours: float = Field(default=0.0, ge=0.0, le=24.0)
    
#     # Week information for efficient querying
#     week_start: datetime = Field(index=True, nullable=False)
#     week_end: datetime = Field(index=True, nullable=False)
    
#     # Status and metadata
#     status: str = Field(default=TimesheetStatus.DRAFT.value, max_length=20)
#     description: Optional[str] = Field(default=None, max_length=500)
    
#     # Timestamps
#     created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
#     updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

#     # Relationships
#     user: "User" = Relationship(back_populates="timesheets")
#     task: Optional["Task"] = Relationship(back_populates="timesheets")
#     organization: Optional["Organization"] = Relationship(back_populates="timesheets")

#     def calculate_week_dates(self):
#         """Calculate week start (Monday) and end (Sunday) for the given date"""
#         # Extract date part for calculation
#         date_obj = self.date.date() if isinstance(self.date, datetime) else self.date
#         weekday = date_obj.weekday()  # Monday is 0, Sunday is 6
#         week_start_date = date_obj - timedelta(days=weekday)
#         week_end_date = week_start_date + timedelta(days=6)  # Sunday
        
#         # Convert back to datetime
#         self.week_start = datetime.combine(week_start_date, datetime.min.time())
#         self.week_end = datetime.combine(week_end_date, datetime.min.time())

#     @property
#     def is_future_date(self) -> bool:
#         """Check if this timesheet entry is for a future date"""
#         from datetime import datetime
#         return self.date.date() > datetime.now(UTC).date() if isinstance(self.date, datetime) else self.date > datetime.now(UTC).date()


# # ============================================================
# # ORGANIZATION (tenant)
# # ============================================================
# class Organization(SQLModel, table=True):
#     __tablename__ = "organization"

#     id: Optional[int] = Field(default=None, primary_key=True)
#     name: str = Field(max_length=100)
#     slug: Optional[str] = Field(default=None, max_length=50, index=True)
#     created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

#     super_admin_id: Optional[int] = Field(foreign_key="user.id", nullable=True, index=True)

#     # ✅ This field links to the currently active payment
#     current_payment_id: Optional[int] = Field(default=None, foreign_key="payment.id", index=True)

#     # ✅ Relationships
#     users: List["User"] = Relationship(
#         back_populates="organization",
#         sa_relationship_kwargs={"foreign_keys": "User.organization_id"}
#     )
#     projects: List["Project"] = Relationship(back_populates="organization")
#     tasks: List["Task"] = Relationship(back_populates="organization")
#     invitations: List["Invitation"] = Relationship(back_populates="organization")
#     payments: List["Payment"] = Relationship(
#         back_populates="organization",
#         sa_relationship_kwargs={"foreign_keys": "[Payment.organization_id]"}
#     )
#     invoices: List["Invoice"] = Relationship(back_populates="organization")
#     webhook_events: List["WebhookEvent"] = Relationship(back_populates="organization")
#     timesheets: List["Timesheet"] = Relationship(back_populates="organization")
#     leave_requests: List["LeaveRequest"] = Relationship(back_populates="organization")
#     leave_balances: List["LeaveBalance"] = Relationship(back_populates="organization")
#     leave_types: List["LeaveType"] = Relationship(back_populates="organization")

#     current_payment: Optional["Payment"] = Relationship(
#         sa_relationship_kwargs={"foreign_keys": "[Organization.current_payment_id]"}
#     )

#     super_admin: Optional["User"] = Relationship(
#         sa_relationship_kwargs={"foreign_keys": "[Organization.super_admin_id]"}
#     )

# # ============================================================
# # USER
# # ============================================================
# class User(SQLModel, table=True):
#     __tablename__ = "user"
#     __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_org_email"),)

#     id: Optional[int] = Field(default=None, primary_key=True)
#     full_name: str = Field(max_length=100)
#     email: EmailStr = Field(index=True, max_length=100, nullable=False)
#     username: Optional[str] = Field(default=None, max_length=50, index=True)
#     password_hash: str = Field(nullable=False)

#     # Role + public marker
#     role: str = Field(default=UserRole.MEMBER.value, max_length=20, index=True)
#     is_public_admin: bool = Field(default=False, index=True, description="True for public signups that are tenant bootstrappers")

#     is_active: bool = Field(default=True)
#     is_invited: bool = Field(default=False)
#     created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
#     date_joined: datetime = Field(default_factory=lambda: datetime.now(UTC))

#     # Profile
#     department: Optional[str] = None
#     job_title: Optional[str] = None
#     profile_picture: Optional[str] = None
#     phone_number: Optional[str] = None
#     time_zone: Optional[str] = None
#     bio: Optional[str] = None
#     skills: Optional[str] = None

#     # Relations
#     organization_id: int = Field(foreign_key="organization.id", index=True)
#     organization: Optional["Organization"] = Relationship(
#         back_populates="users",
#         sa_relationship_kwargs={"foreign_keys": "[User.organization_id]"}
#     )

#     # Relationships
#     projects: List["Project"] = Relationship(back_populates="creator")
#     tasks: List["Task"] = Relationship(back_populates="members", link_model=TaskMemberLink)
#     sent_invitations: List["Invitation"] = Relationship(back_populates="sent_by")
#     comments: List["TaskComment"] = Relationship(back_populates="user")

#     # ✅ Cascade delete work logs when user is deleted
#     work_logs: List["TaskWorkLog"] = Relationship(
#         back_populates="user",
#         sa_relationship_kwargs={"cascade": "all, delete-orphan"}
#     )

#     payments: List["Payment"] = Relationship(back_populates="user")
#     timesheets: List["Timesheet"] = Relationship(back_populates="user")

#     def is_super_admin(self) -> bool:
#         return self.role == UserRole.SUPER_ADMIN.value and self.is_public_admin is True

#     # Add these relationships:
#     leave_requests: List["LeaveRequest"] = Relationship(
#         back_populates="user",
#         sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.user_id]"}
#     )
#     leave_balances: List["LeaveBalance"] = Relationship(
#         back_populates="user",
#         sa_relationship_kwargs={"foreign_keys": "[LeaveBalance.user_id]"}
#     )
#     handover_leave_requests: List["LeaveRequest"] = Relationship(
#         back_populates="handover_person",
#         sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.handover_person_id]"}
#     )
#     approved_leave_requests: List["LeaveRequest"] = Relationship(
#         back_populates="approver",
#         sa_relationship_kwargs={"foreign_keys": "[LeaveRequest.approved_by]"}
#     )

# ============================================================
# PROJECT
# ============================================================
class Project(SQLModel, table=True):
    __tablename__ = "project"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=100, alias="name")
    description: Optional[str] = Field(max_length=500, default=None)
    creator_id: int = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Tenant scoping
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)

    organization: Optional["Organization"] = Relationship(back_populates="projects")
    creator: "User" = Relationship(back_populates="projects")
    tasks: List["Task"] = Relationship(back_populates="project")


# ============================================================
# TASK
# ============================================================
class Task(SQLModel, table=True):
    __tablename__ = "task"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    description: Optional[str] = Field(max_length=1000, default=None)
    status: str = Field(default="Open", max_length=20)
    priority: str = Field(default="medium", max_length=20)
    start_date: Optional[datetime] = None  # ✅ NEW FIELD
    due_date: Optional[datetime] = None
    project_id: int = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    allow_member_edit: bool = Field(default=False)

    # Tenant scoping
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)

    # Relationships (unchanged)
    project: "Project" = Relationship(back_populates="tasks")
    members: List["User"] = Relationship(back_populates="tasks", link_model=TaskMemberLink)
    comments: List["TaskComment"] = Relationship(back_populates="task")
    work_logs: List["TaskWorkLog"] = Relationship(back_populates="task")
    timesheets: List["Timesheet"] = Relationship(back_populates="task")
    organization: Optional["Organization"] = Relationship(back_populates="tasks")

# ============================================================
# TASK COMMENT
# ============================================================
class TaskComment(SQLModel, table=True):
    __tablename__ = "task_comment"
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    user_id: int = Field(foreign_key="user.id")
    message: str = Field(max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Tenant scoping
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)

    task: "Task" = Relationship(back_populates="comments")
    user: "User" = Relationship(back_populates="comments")


# ============================================================
# WORK LOG
# ============================================================
class TaskWorkLog(SQLModel, table=True):
    __tablename__ = "task_work_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", nullable=False)
    user_id: int = Field(foreign_key="user.id", nullable=False)
    hours: float = Field(gt=0)
    description: Optional[str] = Field(max_length=500, default=None)
    date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)

    task: "Task" = Relationship(back_populates="work_logs")

    # ✅ Cascade relationship back to user
    user: "User" = Relationship(
        back_populates="work_logs",
        sa_relationship_kwargs={"cascade": "all, delete"}
    )


# ============================================================
# INVITATION
# ============================================================
class Invitation(SQLModel, table=True):
    __tablename__ = "invitation"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_org_invite_email"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    email: EmailStr = Field(max_length=100, nullable=False, index=True)
    token: str = Field(max_length=255, unique=True, nullable=False, index=True)
    role: str = Field(default=UserRole.MEMBER.value, max_length=20)
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(days=7))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_by_id: int = Field(foreign_key="user.id")
    accepted: bool = Field(default=False)
    accepted_at: Optional[datetime] = None

    # Tenant scoping
    organization_id: int = Field(foreign_key="organization.id", index=True)

    organization: Optional["Organization"] = Relationship(back_populates="invitations")
    sent_by: "User" = Relationship(back_populates="sent_invitations")

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at


# ============================================================
# PRICING PLAN
# ============================================================
class PricingPlan(SQLModel, table=True):
    __tablename__ = "pricingplan"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=50, unique=True, nullable=False)
    slug: Optional[str] = Field(default=None, max_length=50, unique=True)

    # Pricing & Billing
    member_limit: Optional[int] = Field(default=3)
    max_invitations: Optional[int] = Field(default=4, description="Maximum invitations allowed for this plan")
    price_monthly: Optional[float] = Field(default=0.0)
    price_yearly: Optional[float] = Field(default=0.0)
    currency: str = Field(default="USD", max_length=3)
    stripe_price_id_monthly: Optional[str] = Field(default=None, max_length=255)
    stripe_price_id_yearly: Optional[str] = Field(default=None, max_length=255)

    # Features & metadata
    features: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    trial_days: int = Field(default=0)
    description: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Duration (days)
    duration_days: int = Field(default=30, description="Default billing duration for the plan")

    payments: List["Payment"] = Relationship(back_populates="pricing_plan")


# ============================================================
# PAYMENT / SUBSCRIPTION
# ============================================================
class Payment(SQLModel, table=True):
    __tablename__ = "payment"

    id: Optional[int] = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)
    user_id: int = Field(foreign_key="user.id", nullable=False, index=True)

    plan_name: str = Field(default=PlanName.FREE.value, max_length=50, index=True)
    pricing_plan_id: Optional[int] = Field(default=None, foreign_key="pricingplan.id", index=True)
    billing_cycle: str = Field(default=BillingCycle.MONTHLY.value, max_length=20)

    stripe_subscription_id: Optional[str] = Field(default=None, max_length=255, index=True)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255, index=True)
    stripe_price_id: Optional[str] = Field(default=None, max_length=255)

    status: str = Field(default=PaymentStatus.ACTIVE.value, max_length=20)
    current_period_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_period_end: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(days=30))
    cancel_at_period_end: bool = Field(default=False)

    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    grace_period_until: Optional[datetime] = None
    canceled_at: Optional[datetime] = None

    payment_metadata: Optional[str] = None
    transaction_data: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    organization: Optional["Organization"] = Relationship(
        back_populates="payments",
        sa_relationship_kwargs={"foreign_keys": "[Payment.organization_id]"}
    )
    user: "User" = Relationship(back_populates="payments")
    pricing_plan: Optional["PricingPlan"] = Relationship(back_populates="payments")
    invoices: List["Invoice"] = Relationship(back_populates="payment")

    @property
    def is_active_subscription(self) -> bool:
        return (
            self.status == PaymentStatus.ACTIVE.value
            and self.current_period_end > datetime.now(UTC)
        )


# ============================================================
# INVOICE
# ============================================================
class Invoice(SQLModel, table=True):
    __tablename__ = "invoice"
    id: Optional[int] = Field(default=None, primary_key=True)
    payment_id: int = Field(foreign_key="payment.id", nullable=False, index=True)
    organization_id: int = Field(foreign_key="organization.id", nullable=False, index=True)

    invoice_number: str = Field(unique=True, index=True, max_length=100)
    stripe_invoice_id: Optional[str] = Field(default=None, max_length=255, index=True)
    amount_due: float = Field(default=0.0)
    amount_paid: float = Field(default=0.0)
    currency: str = Field(default="USD", max_length=3)

    billing_period_start: datetime = Field(default_factory=lambda: datetime.now(UTC))
    billing_period_end: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(days=30))

    status: str = Field(default="draft", max_length=20)
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    payment: "Payment" = Relationship(back_populates="invoices")
    organization: "Organization" = Relationship(back_populates="invoices")


# ============================================================
# WEBHOOK EVENT LOG
# ============================================================
class WebhookEvent(SQLModel, table=True):
    __tablename__ = "webhook_event"
    id: Optional[int] = Field(default=None, primary_key=True)
    stripe_event_id: str = Field(unique=True, index=True, max_length=255)
    event_type: str = Field(max_length=100, index=True)

    payload: str = Field()
    processed: bool = Field(default=False)
    processing_error: Optional[str] = None

    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    organization: Optional["Organization"] = Relationship(back_populates="webhook_events")


# ============================================================
# ORGANIZATION MEMBER COUNT (virtual)
# ============================================================
class OrganizationMemberCount(SQLModel):
    organization_id: int
    total_members: int
    active_members: int
    member_limit: Optional[int]
    can_add_more: bool


# ============================================================
# MEMBER LIMIT UTILITIES
# ============================================================
class MemberLimitUtils:
    """Utility functions for member/invitation limit management"""

    @staticmethod
    def get_plan_limits(plan_name: str) -> Optional[int]:
        limits = {
            PlanName.FREE.value: 4,
            PlanName.PRO.value: 11,
            PlanName.TEAM.value: None,
        }
        return limits.get(plan_name, 3)

    @staticmethod
    def can_organization_add_member(organization_plan_name: str, current_member_count: int) -> bool:
        """True if organization can add/invite another member"""
        plan_limit = MemberLimitUtils.get_plan_limits(organization_plan_name)
        if plan_limit is None:
            return True
        return current_member_count < plan_limit

    @staticmethod
    def default_pricing_plans() -> List[Dict]:
        return [
            {
                "name": PlanName.FREE.value,
                "slug": "free",
                "max_invitations": 4,
                "price_monthly": 0.0,
                "price_yearly": 0.0,
                "duration_days": 30,
                "trial_days": 0,
            },
            {
                "name": PlanName.PRO.value,
                "slug": "pro",
                "max_invitations": 11,
                "price_monthly": 29.0,
                "price_yearly": 290.0,
                "duration_days": 30,
                "trial_days": 14,
            },
            {
                "name": PlanName.TEAM.value,
                "slug": "team",
                "max_invitations": None,
                "price_monthly": 99.0,
                "price_yearly": 990.0,
                "duration_days": 30,
                "trial_days": 14,
            },
        ]


# ============================================================
# SUBSCRIPTION SERVICE (implemented)
# ============================================================
from sqlalchemy import select

class SubscriptionService:
    """
    Service-level helpers for subscription management:
    - Auto-expiry and downgrade handling
    - Stripe webhook event processing
    """

    @staticmethod
    def get_effective_plan(payment: "Payment") -> Dict:
        if not payment or not payment.pricing_plan:
            return {"name": PlanName.FREE.value, "max_invitations": 4}

        plan = payment.pricing_plan
        return {
            "name": plan.name,
            "max_invitations": getattr(plan, "max_invitations", getattr(plan, "member_limit", 4)),
            "duration_days": getattr(plan, "duration_days", 30),
            "is_active": plan.is_active,
        }
    
    # ... existing methods ...

    @staticmethod
    def update_subscription(session, organization_id: int, user_id: int, new_plan: str):
        """
        Upgrade or downgrade an organization's subscription plan.
        Enforces member limits when downgrading.
        """
        now = datetime.now(UTC)

        # Get org and current payment
        org = session.get(Organization, organization_id)
        current_payment = (
            session.exec(
                select(Payment)
                .where(Payment.organization_id == organization_id)
                .order_by(Payment.created_at.desc())
            ).first()
        )

        # Get member count
        member_count = session.exec(
            select(User).where(User.organization_id == organization_id)
        ).count()

        # Determine limits
        limits = MemberLimitUtils.get_plan_limits(new_plan)

        # ✅ Downgrade constraint check
        if limits is not None and member_count > limits:
            return {
                "success": False,
                "message": f"Please remove members until your total is {limits} or fewer before switching to the {new_plan} plan.",
            }

        # ✅ Deactivate old payments
        session.exec(
            select(Payment)
            .where(Payment.organization_id == organization_id, Payment.status == PaymentStatus.ACTIVE.value)
        )
        for pay in org.payments:
            if pay.status == PaymentStatus.ACTIVE.value:
                pay.status = PaymentStatus.INACTIVE.value

        # ✅ Get pricing plan
        pricing_plan = session.exec(
            select(PricingPlan).where(PricingPlan.name == new_plan)
        ).first()

        # ✅ Create new active payment
        new_payment = Payment(
            organization_id=organization_id,
            user_id=user_id,
            plan_name=new_plan,
            pricing_plan_id=pricing_plan.id if pricing_plan else None,
            billing_cycle=BillingCycle.MONTHLY.value,
            status=PaymentStatus.ACTIVE.value,
            current_period_start=now,
            current_period_end=now + timedelta(days=pricing_plan.duration_days if pricing_plan else 30),
        )
        session.add(new_payment)
        session.commit()

        # ✅ Update organization pointer
        org.current_payment_id = new_payment.id
        session.commit()

        return {
            "success": True,
            "message": f"Subscription successfully updated to {new_plan} plan.",
            "plan": new_plan,
        }


    # ------------------------------------------------------------
    # AUTO-EXPIRY HANDLER (for cron)
    # ------------------------------------------------------------
    @staticmethod
    def handle_subscription_expiry(session):
        """
        Find payments that have expired (period_end < now) and are not active.
        Downgrade such organizations to Free plan.
        """
        now = datetime.now(UTC)
        stmt = select(Payment).where(
            Payment.current_period_end < now,
            Payment.status.not_in([PaymentStatus.CANCELLED.value, PaymentStatus.EXPIRED.value]),
        )
        expired_payments = session.exec(stmt).all()

        for pay in expired_payments:
            # Mark as expired
            pay.status = PaymentStatus.EXPIRED.value
            pay.updated_at = now

            # Downgrade organization to Free plan
            free_plan_stmt = select(PricingPlan).where(PricingPlan.name == PlanName.FREE.value)
            free_plan = session.exec(free_plan_stmt).first()

            # Create new free-tier payment entry (optional)
            new_payment = Payment(
                organization_id=pay.organization_id,
                user_id=pay.user_id,
                plan_name=PlanName.FREE.value,
                pricing_plan_id=free_plan.id if free_plan else None,
                billing_cycle=BillingCycle.MONTHLY.value,
                status=PaymentStatus.ACTIVE.value,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            session.add(new_payment)

        session.commit()
        return len(expired_payments)

    # ------------------------------------------------------------
    # STRIPE WEBHOOK PROCESSOR
    # ------------------------------------------------------------
    @staticmethod
    def process_webhook_event(event_data: dict, session):
        """
        Process Stripe webhook events safely with idempotency check.
        """
        event_id = event_data.get("id")
        event_type = event_data.get("type")

        # Idempotency check
        existing = session.exec(
            select(WebhookEvent).where(WebhookEvent.stripe_event_id == event_id)
        ).first()
        if existing:
            return {"status": "ignored", "reason": "already_processed"}

        # Log webhook event
        webhook_event = WebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=json.dumps(event_data),
            processed=False,
            created_at=datetime.now(UTC),
        )
        session.add(webhook_event)
        session.commit()

        try:
            data_object = event_data.get("data", {}).get("object", {})
            stripe_sub_id = data_object.get("subscription") or data_object.get("id")

            if not stripe_sub_id:
                webhook_event.processing_error = "Missing subscription id"
                webhook_event.processed = False
                session.commit()
                return {"status": "error", "reason": "no_subscription_id"}

            # Fetch payment by stripe_subscription_id
            payment = session.exec(
                select(Payment).where(Payment.stripe_subscription_id == stripe_sub_id)
            ).first()

            if not payment:
                webhook_event.processing_error = "No matching Payment record"
                session.commit()
                return {"status": "error", "reason": "payment_not_found"}

            now = datetime.now(UTC)

            # Handle event types
            if event_type == "invoice.paid":
                # Payment succeeded — extend subscription
                payment.status = PaymentStatus.ACTIVE.value
                payment.current_period_start = now
                payment.current_period_end = now + timedelta(days=30)

            elif event_type in ["invoice.payment_failed", "customer.subscription.deleted"]:
                payment.status = PaymentStatus.CANCELLED.value
                payment.canceled_at = now

            elif event_type == "customer.subscription.updated":
                # Update billing cycle or trial period if present
                trial_end = data_object.get("trial_end")
                if trial_end:
                    payment.trial_end = datetime.utcfromtimestamp(trial_end)

                payment.updated_at = now

            # Finalize
            webhook_event.processed = True
            session.commit()

            return {"status": "ok", "event_type": event_type}

        except Exception as e:
            webhook_event.processing_error = str(e)
            webhook_event.processed = False
            session.commit()
            return {"status": "error", "reason": str(e)}
            


# ============================================================
# DEFAULT PRICING PLANS (constant)
# ============================================================
DEFAULT_PRICING_PLANS = MemberLimitUtils.default_pricing_plans()


# ============================================================
# EXPORTS
# ============================================================
__all__ = [
    "Organization",
    "User",
    "Project",
    "Task",
    "TaskComment",
    "TaskWorkLog",
    "Invitation",
    "PricingPlan",
    "Payment",
    "Invoice",
    "WebhookEvent",
    "Timesheet",  # ✅ Added Timesheet to exports
    "TimesheetStatus",  # ✅ Added TimesheetStatus to exports
    "OrganizationMemberCount",
    "MemberLimitUtils",
    "SubscriptionService",
    "UserRole",
    "PlanName",
    "PaymentStatus",
    "BillingCycle",
    "InvitationStatus",
    "DEFAULT_PRICING_PLANS",
]