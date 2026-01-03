# payment_schema.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


class PlanName(str, Enum):
    FREE = "Free"
    PRO = "Pro"
    TEAM = "Team"


class PaymentStatus(str, Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    PENDING = "pending"


class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


# ---------------------------
# Pricing Plan
# ---------------------------
class PricingPlanCreate(BaseModel):
    name: str = Field(..., max_length=50)
    slug: Optional[str] = Field(default=None, max_length=50)
    member_limit: Optional[int] = Field(default=4)
    max_invitations: Optional[int] = Field(default=4, description="Maximum invitations allowed for this plan")
    price_monthly: Optional[float] = Field(default=0.0)
    price_yearly: Optional[float] = Field(default=0.0)
    currency: str = Field(default="USD", max_length=3)
    stripe_price_id_monthly: Optional[str] = Field(default=None, max_length=255)
    stripe_price_id_yearly: Optional[str] = Field(default=None, max_length=255)
    features: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    trial_days: int = Field(default=0)
    description: Optional[str] = Field(default=None, max_length=500)
    duration_days: int = Field(default=30, description="Default billing duration for the plan")


class PricingPlanRead(BaseModel):
    id: int
    name: str
    slug: Optional[str]
    member_limit: Optional[int]
    max_invitations: Optional[int]
    price_monthly: Optional[float]
    price_yearly: Optional[float]
    currency: str
    stripe_price_id_monthly: Optional[str]
    stripe_price_id_yearly: Optional[str]
    features: Optional[str]
    is_active: bool
    trial_days: int
    description: Optional[str]
    duration_days: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PricingPlanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=50)
    slug: Optional[str] = Field(default=None, max_length=50)
    member_limit: Optional[int] = Field(default=3)
    max_invitations: Optional[int] = Field(default=4, description="Maximum invitations allowed for this plan")
    price_monthly: Optional[float] = Field(default=0.0)
    price_yearly: Optional[float] = Field(default=0.0)
    currency: str = Field(default="USD", max_length=3)
    stripe_price_id_monthly: Optional[str] = Field(default=None, max_length=255)
    stripe_price_id_yearly: Optional[str] = Field(default=None, max_length=255)
    features: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=True)
    trial_days: Optional[int] = Field(default=0)
    description: Optional[str] = Field(default=None, max_length=500)
    duration_days: Optional[int] = Field(default=30, description="Default billing duration for the plan")


# ---------------------------
# Payment / Subscription
# ---------------------------
class PaymentCreate(BaseModel):
    organization_id: int
    user_id: int
    plan_name: str = Field(default="Free", max_length=50)
    pricing_plan_id: Optional[int] = Field(default=None)
    billing_cycle: str = Field(default="monthly", max_length=20)
    stripe_subscription_id: Optional[str] = Field(default=None, max_length=255)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    stripe_price_id: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(default="active", max_length=20)
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = Field(default=False)
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    grace_period_until: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    payment_metadata: Optional[str] = Field(default=None)
    transaction_data: Optional[str] = Field(default=None)


class PaymentRead(BaseModel):
    id: int
    organization_id: int
    user_id: int
    plan_name: str
    pricing_plan_id: Optional[int]
    billing_cycle: str
    stripe_subscription_id: Optional[str]
    stripe_customer_id: Optional[str]
    stripe_price_id: Optional[str]
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    trial_start: Optional[datetime]
    trial_end: Optional[datetime]
    grace_period_until: Optional[datetime]
    canceled_at: Optional[datetime]
    payment_metadata: Optional[str]
    transaction_data: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentUpdate(BaseModel):
    pricing_plan_id: Optional[int] = None
    plan_name: Optional[str] = Field(default=None, max_length=50)
    billing_cycle: Optional[str] = Field(default=None, max_length=20)
    stripe_subscription_id: Optional[str] = Field(default=None, max_length=255)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    stripe_price_id: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, max_length=20)
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    grace_period_until: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    payment_metadata: Optional[str] = Field(default=None)
    transaction_data: Optional[str] = Field(default=None)


# ---------------------------
# Invoice
# ---------------------------
class InvoiceCreate(BaseModel):
    payment_id: int
    organization_id: int
    invoice_number: str = Field(..., max_length=100)
    stripe_invoice_id: Optional[str] = Field(default=None, max_length=255)
    amount_due: float = Field(default=0.0)
    amount_paid: float = Field(default=0.0)
    currency: str = Field(default="USD", max_length=3)
    billing_period_start: Optional[datetime] = None
    billing_period_end: Optional[datetime] = None
    status: str = Field(default="draft", max_length=20)
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None


class InvoiceRead(BaseModel):
    id: int
    payment_id: int
    organization_id: int
    invoice_number: str
    stripe_invoice_id: Optional[str]
    amount_due: float
    amount_paid: float
    currency: str
    billing_period_start: datetime
    billing_period_end: datetime
    status: str
    due_date: Optional[datetime]
    paid_at: Optional[datetime]
    hosted_invoice_url: Optional[str]
    invoice_pdf: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------
# Webhook Event
# ---------------------------
class WebhookEventCreate(BaseModel):
    stripe_event_id: str = Field(..., max_length=255)
    event_type: str = Field(..., max_length=100)
    payload: str
    organization_id: Optional[int] = None


class WebhookEventRead(BaseModel):
    id: int
    stripe_event_id: str
    event_type: str
    payload: str
    processed: bool
    processing_error: Optional[str] = None
    organization_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebhookEventUpdate(BaseModel):
    processed: Optional[bool] = None
    processing_error: Optional[str] = None
