# profile_schema.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ProfileRead(BaseModel):
    id: int
    full_name: str = Field(..., max_length=100)
    email: EmailStr
    username: Optional[str] = Field(default=None, max_length=50)
    password_hash: Optional[str] = None
    role: str = Field(..., max_length=20)
    is_public_admin: bool = Field(default=False)
    is_active: bool = Field(default=True)
    is_invited: bool = Field(default=False)
    created_at: datetime
    date_joined: datetime
    department: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture: Optional[str] = None
    phone_number: Optional[str] = None
    time_zone: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=20)
    is_active: Optional[bool] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture: Optional[str] = None
    phone_number: Optional[str] = None
    time_zone: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None
