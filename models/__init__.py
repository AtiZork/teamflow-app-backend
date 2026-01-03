# backend/models/__init__.py
# import every SQLModel-table so metadata.register() runs
# models/__init__.py (update)
from .models import User, Organization, Project, Task, TaskComment, TaskWorkLog, Invitation, PricingPlan, Payment, Invoice, WebhookEvent
from .attendance_models import Attendance, ActiveSession, BreakHistory  # ✅ Added
from .leave_models import LeaveRequest, LeaveType, LeaveBalance  # ✅ Added

__all__ = [
    "User",
    "Organization",
    "Project",
    "Task", 
    "TaskComment",
    "TaskWorkLog",
    "Invitation",
    "PricingPlan",
    "Payment",
    "Invoice",
    "WebhookEvent",
    "Attendance",  # ✅ Added
    "ActiveSession",  # ✅ Added
    "BreakHistory",  # ✅ Added
    "LeaveRequest",
    "LeaveType",
    "LeaveBalance",
]