# # user_schema.py
# from pydantic import BaseModel, EmailStr, Field, ConfigDict
# from typing import Optional
# from datetime import datetime
# from enum import Enum


# class UserRole(str, Enum):
#     SUPER_ADMIN = "super_admin"
#     ADMIN = "admin"
#     MEMBER = "member"


# # ---------------------------
# # Create & Auth
# # ---------------------------
# class UserCreate(BaseModel):
#     full_name: str = Field(..., min_length=1, max_length=100)
#     email: EmailStr
#     password: str = Field(..., min_length=8)
#     username: Optional[str] = Field(default=None, max_length=50)
#     # For public signups, server will set role=SUPER_ADMIN and is_public_admin=True

# class UserLogin(BaseModel):
#     email: EmailStr
#     password: str


# # ---------------------------
# # Read / Update
# # ---------------------------
# class UserRead(BaseModel):
#     id: int
#     full_name: str = Field(..., max_length=100)
#     email: EmailStr
#     username: Optional[str] = Field(default=None, max_length=50)
#     password_hash: Optional[str] = None
#     role: str = Field(..., max_length=20)
#     is_public_admin: bool = Field(default=False)
#     is_active: bool = Field(default=True)
#     is_invited: bool = Field(default=False)
#     created_at: datetime
#     date_joined: datetime
#     department: Optional[str] = None
#     job_title: Optional[str] = None
#     profile_picture: Optional[str] = None
#     phone_number: Optional[str] = None
#     time_zone: Optional[str] = None
#     bio: Optional[str] = None
#     skills: Optional[str] = None
#     organization_id: Optional[int] = None

#     model_config = ConfigDict(from_attributes=True)


# class UserUpdate(BaseModel):
#     full_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
#     email: Optional[EmailStr] = None
#     username: Optional[str] = Field(default=None, max_length=50)
#     role: Optional[str] = Field(default=None, max_length=20)
#     is_public_admin: Optional[bool] = None
#     is_active: Optional[bool] = None
#     is_invited: Optional[bool] = None
#     department: Optional[str] = None
#     job_title: Optional[str] = None
#     profile_picture: Optional[str] = None
#     phone_number: Optional[str] = None
#     time_zone: Optional[str] = None
#     bio: Optional[str] = None
#     skills: Optional[str] = None


# class AccountActivate(BaseModel):
#     token: str
#     full_name: str
#     password: str = Field(..., min_length=8)


# class UserWithOrganization(BaseModel):
#     id: int
#     full_name: str
#     email: str
#     role: str
#     is_active: bool
#     organization_id: Optional[int] = None
#     organization_name: Optional[str] = None
#     is_super_admin: bool = False

#     model_config = ConfigDict(from_attributes=True)


















# user_schema.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MEMBER = "member"


# ---------------------------
# Create & Auth
# ---------------------------
class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: Optional[str] = Field(default=None, max_length=50)
    # For public signups, server will set role=SUPER_ADMIN and is_public_admin=True
    organization_id: Optional[int] = None  # Added for context


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ---------------------------
# Read / Update
# ---------------------------
class UserRead(BaseModel):
    id: int
    full_name: str = Field(..., max_length=100)
    email: EmailStr
    username: Optional[str] = Field(default=None, max_length=50)
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
    organization_id: int  # MADE REQUIRED for isolation
    
    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=20)
    is_public_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    is_invited: Optional[bool] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    profile_picture: Optional[str] = None
    phone_number: Optional[str] = None
    time_zone: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None
    organization_id: Optional[int] = None  # Added


class AccountActivate(BaseModel):
    token: str
    full_name: str
    password: str = Field(..., min_length=8)


class UserWithOrganization(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    organization_id: int  # MADE REQUIRED
    organization_name: Optional[str] = None
    is_super_admin: bool = False
    
    model_config = ConfigDict(from_attributes=True)


# New: User with leave context
class UserWithLeaveContext(BaseModel):
    """User with organization and leave context"""
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    organization_id: int
    department: Optional[str] = None
    job_title: Optional[str] = None
    has_leave_access: bool = True  # Default to True, can be restricted
    
    model_config = ConfigDict(from_attributes=True)