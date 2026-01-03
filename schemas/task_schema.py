# task_schema.py
from pydantic import BaseModel, Field, ConfigDict, validator
from typing import Annotated, Optional, List
from datetime import datetime


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(default="Open", max_length=20)
    priority: str = Field(default="medium", max_length=20)
    start_date: Optional[datetime] = None  # ✅ NEW FIELD
    due_date: Optional[datetime] = None
    project_id: int
    allow_member_edit: bool = Field(default=False)
    member_ids: Optional[List[int]] = Field(default=[])

    @validator('member_ids', pre=True)
    def validate_member_ids(cls, v):
        if v is None:
            return []
        return v


class TaskRead(BaseModel):
    id: int
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(..., max_length=20)
    priority: str = Field(..., max_length=20)
    start_date: Optional[datetime] = None  # ✅ NEW FIELD
    due_date: Optional[datetime] = None
    project_id: int
    project_name: Optional[str] = None
    created_at: datetime
    allow_member_edit: bool = Field(default=False)
    organization_id: Optional[int] = None
    member_ids: List[int] = Field(default=[])
    member_names: List[str] = Field(default=[])

    model_config = ConfigDict(from_attributes=True)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default=None, max_length=20)
    priority: Optional[str] = Field(default=None, max_length=20)
    start_date: Optional[datetime] = None  # ✅ NEW FIELD
    due_date: Optional[datetime] = None
    project_id: Optional[int] = None
    allow_member_edit: Optional[bool] = None
    member_ids: Optional[List[int]] = Field(default=[])

    @validator('member_ids', pre=True)
    def validate_member_ids(cls, v):
        if v is None:
            return []
        return v


# Also update TaskOut schema for search results
class TaskOut(BaseModel):
    id: int
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(..., max_length=20)
    priority: str = Field(..., max_length=20)
    start_date: Optional[datetime] = None  # ✅ NEW FIELD
    due_date: Optional[datetime] = None
    project_id: int
    project_name: Optional[str] = None
    created_at: datetime
    allow_member_edit: bool = Field(default=False)
    organization_id: Optional[int] = None
    member_ids: List[int] = Field(default=[])
    member_names: List[str] = Field(default=[])

    model_config = ConfigDict(from_attributes=True)



# Comments
class CommentCreate(BaseModel):
    message: str = Field(..., max_length=2000)


class CommentRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    message: str = Field(..., max_length=2000)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Worklogs
class WorkLogCreate(BaseModel):
    hours: float = Field(..., gt=0)
    description: Optional[str] = Field(default=None, max_length=500)
    date: Optional[datetime] = None
    
    @validator('date', pre=True)
    def parse_date(cls, value):
        if isinstance(value, str):
            # Handle both ISO format with and without timezone
            if value.endswith('Z'):
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                return datetime.fromisoformat(value)
        return value


class WorkLogRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    hours: float
    description: Optional[str]
    date: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Task Member Link
class TaskMemberLinkCreate(BaseModel):
    task_id: int
    user_id: int
    organization_id: Optional[int] = None


class TaskMemberLinkRead(BaseModel):
    task_id: int
    user_id: int
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# Task Comment
class TaskCommentCreate(BaseModel):
    task_id: int
    user_id: int
    message: str = Field(..., max_length=2000)
    organization_id: Optional[int] = None


class TaskCommentRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    message: str = Field(..., max_length=2000)
    created_at: datetime
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class TaskCommentUpdate(BaseModel):
    message: Optional[str] = Field(default=None, max_length=2000)


# Task Work Log
class TaskWorkLogCreate(BaseModel):
    task_id: int
    user_id: int
    hours: float = Field(..., gt=0)
    description: Optional[str] = Field(default=None, max_length=500)
    date: Optional[datetime] = None
    organization_id: Optional[int] = None


class TaskWorkLogRead(BaseModel):
    id: int
    task_id: int
    user_id: int
    hours: float
    description: Optional[str]
    date: datetime
    created_at: datetime
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class TaskWorkLogUpdate(BaseModel):
    hours: Optional[float] = Field(default=None, gt=0)
    description: Optional[str] = Field(default=None, max_length=500)
    date: Optional[datetime] = None


# Add this search schemas
class TaskSearchSchema(BaseModel):
    from_date: Optional[datetime] = Field(default=None, alias="fromDate")
    to_date: Optional[datetime] = Field(default=None, alias="toDate")
    title: Optional[str] = Field(default=None, max_length=200)
    status: Optional[str] = Field(default=None, max_length=20)
    priority: Optional[str] = Field(default=None, max_length=20)
    assigned_to: Optional[str] = Field(default=None, alias="assignedTo")

    model_config = ConfigDict(populate_by_name=True)

