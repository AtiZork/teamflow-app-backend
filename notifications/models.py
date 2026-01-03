from typing import Optional, List
from datetime import datetime, UTC
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum

class NotificationType(str, Enum):
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_STATUS_CHANGED = "TASK_STATUS_CHANGED"
    LEAVE_APPLIED = "LEAVE_APPLIED"
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"

class Notification(SQLModel, table=True):
    __tablename__ = "notification"

    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Organization linkage (Multi-tenancy)
    organization_id: int = Field(foreign_key="organization.id", index=True, nullable=False)
    
    # Who triggered it
    sender_id: Optional[int] = Field(default=None, foreign_key="user.id")
    
    # Content
    type: str = Field(max_length=50, index=True)  # Store enum value
    title: str = Field(max_length=200)
    message: str = Field(max_length=500)
    
    # Linked Entity (Polymorphic-ish)
    entity_type: str = Field(max_length=50, index=True) # e.g., "task"
    entity_id: int = Field(index=True)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    recipients: List["NotificationRecipient"] = Relationship(back_populates="notification")

class NotificationRecipient(SQLModel, table=True):
    __tablename__ = "notification_recipient"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    notification_id: int = Field(foreign_key="notification.id", nullable=False, index=True)
    user_id: int = Field(foreign_key="user.id", nullable=False, index=True)
    
    is_read: bool = Field(default=False)
    read_at: Optional[datetime] = None
    
    # Relationships
    notification: Notification = Relationship(back_populates="recipients")

class NotificationRead(SQLModel):
    id: int
    type: str
    title: str
    message: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: datetime
    is_read: bool
    read_at: Optional[datetime] = None
