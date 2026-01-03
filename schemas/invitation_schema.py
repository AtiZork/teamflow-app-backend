from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


# ============================================================
# ✅ Create Invitation (input)
# ============================================================
class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(default="member", max_length=20)
    # organization_id is set server-side (from inviter’s org)
    # sent_by_id is also set server-side (from current user)
    # token and expiry are generated server-side


# ============================================================
# ✅ Read Invitation (output)
# ============================================================
class InvitationRead(BaseModel):
    id: int
    email: EmailStr
    token: str
    role: str
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime

    sent_by_id: Optional[int] = None
    accepted: bool = False
    accepted_at: Optional[datetime] = None
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# ✅ Update Invitation (for marking accepted)
# ============================================================
class InvitationUpdate(BaseModel):
    accepted: Optional[bool] = None
    accepted_at: Optional[datetime] = None


# ============================================================
# ✅ Accept Invitation (for frontend user registration)
# ============================================================
class InvitationAccept(BaseModel):
    token: str
    full_name: str
    password: str = Field(..., min_length=8)
