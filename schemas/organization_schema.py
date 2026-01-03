# organization_schema.py
from pydantic import BaseModel, Field, ConfigDict
from schemas.payment_schema import PaymentRead
from typing import Optional
from datetime import datetime


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(default=None, max_length=50)
    model_config = ConfigDict(from_attributes=True)

    # super_admin_id is set by server during creation


class OrganizationRead(BaseModel):
    id: int
    name: str
    slug: Optional[str] = None
    super_admin_id: Optional[int] = None
    created_at: datetime
    # ✅ NEW FIELD (matches Organization model)
    current_payment_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    
class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    slug: Optional[str] = Field(default=None, max_length=50)
    current_payment_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)
    # super_admin_id cannot be updated via this endpoint



class OrganizationWithSuperAdmin(OrganizationRead):
    super_admin_name: Optional[str] = None
    super_admin_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)



class OrganizationWithPayment(OrganizationRead):
    has_active_payment: bool = False
    current_plan: Optional[str] = None
    current_payment: Optional[PaymentRead] = None 
    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberCountRead(BaseModel):
    organization_id: int
    total_members: int
    active_members: int
    member_limit: Optional[int]
    can_add_more: bool

    model_config = ConfigDict(from_attributes=True)
