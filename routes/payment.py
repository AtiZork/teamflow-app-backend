# routes/payment.py
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from core.config import settings
import asyncio
import stripe

from fastapi import APIRouter, Depends, HTTPException, status, Body, Request, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session, select
from fastapi.responses import JSONResponse

from core.database import get_session
from core.security import get_current_user
from models.models import User, Payment, Organization, PricingPlan, PlanName, PaymentStatus, UserRole, BillingCycle

router = APIRouter(prefix="/payments", tags=["Payments"])

# Stripe integration
import stripe
import os

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize Stripe with environment variables
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Get Stripe Price IDs from environment
STRIPE_PRO_MONTHLY_PRICE_ID = os.getenv("STRIPE_PRO_MONTHLY_PRICE_ID")
STRIPE_TEAM_MONTHLY_PRICE_ID = os.getenv("STRIPE_TEAM_MONTHLY_PRICE_ID")
STRIPE_FREE_PRICE_ID = os.getenv("STRIPE_FREE_PRICE_ID")

# Validate Stripe configuration
if not stripe.api_key:
    raise ValueError("❌ STRIPE_SECRET_KEY is not set in the environment")

if not all([STRIPE_PRO_MONTHLY_PRICE_ID, STRIPE_TEAM_MONTHLY_PRICE_ID, STRIPE_FREE_PRICE_ID]):
    raise ValueError("❌ One or more Stripe Price IDs are missing from environment variables")

print("✅ Stripe configuration loaded successfully")
print(f"💰 Pro Plan Price ID: {STRIPE_PRO_MONTHLY_PRICE_ID}")
print(f"💰 Team Plan Price ID: {STRIPE_TEAM_MONTHLY_PRICE_ID}")
print(f"💰 Free Plan Price ID: {STRIPE_FREE_PRICE_ID}")

# -------------------------
# Request / Response models
# -------------------------
class VisibilityResponse(BaseModel):
    show_payment: bool
    user_role: str
    is_super_admin: bool
    is_invited: bool


class PlanOut(BaseModel):
    id: int
    name: str
    slug: Optional[str]
    member_limit: Optional[int]
    description: Optional[str]
    features: List[str]
    price_monthly: Optional[float]
    price_yearly: Optional[float]
    stripe_price_id_monthly: Optional[str]
    stripe_price_id_yearly: Optional[str]


class CheckoutSessionRequest(BaseModel):
    price_id: str


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class ActiveSubscriptionOut(BaseModel):
    id: int
    organization_id: int
    user_id: int
    plan_name: str
    pricing_plan_id: Optional[int]
    stripe_subscription_id: Optional[str]
    status: str
    start_date: datetime
    end_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class PaymentHistoryOut(BaseModel):
    id: int
    plan_name: str
    pricing_plan_id: Optional[int]
    status: str
    start_date: datetime
    end_date: Optional[datetime]
    created_at: datetime


# -------------------------
# Helper Functions
# -------------------------
def require_public_super_admin(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
) -> User:
    """Dependency that only allows public super admins (tenant owners)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    
    if current_user.role != UserRole.SUPER_ADMIN.value or not current_user.is_public_admin:
        raise HTTPException(status_code=403, detail="Only organization owners can manage payments.")
    
    org = session.get(Organization, current_user.organization_id)
    if not org or org.super_admin_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only organization owners can manage payments.")
    
    return current_user


def verify_payment_access(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
) -> bool:
    """Dependency to verify user has payment access"""
    is_owner = (current_user.role == UserRole.SUPER_ADMIN.value and current_user.is_public_admin)
    
    if not is_owner:
        raise HTTPException(status_code=403, detail="Payment features are only available to organization owners")
    
    org = session.get(Organization, current_user.organization_id)
    if not org or org.super_admin_id != current_user.id:
        raise HTTPException(status_code=403, detail="Payment features are only available to organization owners")
    
    return True


def get_plan_features(plan_name: str) -> List[str]:
    """Get features for each plan based on plan name."""
    features_map = {
        PlanName.FREE: ["Basic usage", "Up to 3 members", "Essential task management"],
        PlanName.PRO: ["Up to 10 members", "Priority support", "Advanced analytics", "Custom fields"],
        PlanName.TEAM: ["Unlimited members", "Advanced analytics", "API access", "Dedicated support", "Custom branding"]
    }
    return features_map.get(plan_name, ["Basic features"])


def get_organization_member_count(organization_id: int, session: Session) -> int:
    """Get current member count for organization"""
    statement = select(User).where(
        User.organization_id == organization_id,
        User.is_active == True
    )
    users = session.exec(statement).all()
    return len(users)


def get_plan_member_limit(plan_name: str) -> int:
    """Get member limit for each plan"""
    limits = {
        PlanName.FREE.value: 4,
        PlanName.PRO.value: 11,
        PlanName.TEAM.value: 9999  # Essentially unlimited
    }
    return limits.get(plan_name, 3)


def enforce_plan_limits(organization_id: int, session: Session) -> None:
    """
    ENFORCEMENT LOGIC: Check if organization can add more members based on current plan
    Raises HTTPException if limit exceeded
    """
    # Get current active subscription
    statement = select(Payment).where(
        Payment.organization_id == organization_id,
        Payment.status == PaymentStatus.ACTIVE
    )
    subscription = session.exec(statement).first()
    
    if not subscription:
        # No active subscription = Free plan limits
        plan_limit = 4
    else:
        plan_limit = get_plan_member_limit(subscription.plan_name)
    
    # Check if subscription is expired
    if subscription and subscription.current_period_end < datetime.utcnow():
        raise HTTPException(
            status_code=403,
            detail="Your subscription has expired. Please renew to add more members."
        )
    
    # Get current member count
    current_members = get_organization_member_count(organization_id, session)
    
    # Enforce limit
    if current_members >= plan_limit:
        raise HTTPException(
            status_code=403,
            detail=f"Member limit reached. Your {subscription.plan_name if subscription else 'Free'} plan allows maximum {plan_limit} members."
        )


############################################## get_current_subscription_for_org ##############################################

def get_current_subscription_for_org(organization_id: int, session: Session) -> Optional[Payment]:
    """Get current active subscription for organization"""
    statement = select(Payment).where(
        Payment.organization_id == organization_id,
        Payment.status == PaymentStatus.ACTIVE
    )
    return session.exec(statement).first()


async def check_and_expire_subscriptions(session: Session):
    """
    BACKGROUND TASK: Check for expired subscriptions and mark them as expired
    Also automatically downgrade to Free plan if expired
    """
    try:
        now = datetime.utcnow()
        
        # Find active subscriptions that have expired
        statement = select(Payment).where(
            Payment.status == PaymentStatus.ACTIVE,
            Payment.current_period_end < now
        )
        expired_subs = session.exec(statement).all()
        
        for subscription in expired_subs:
            print(f"🔄 Auto-expiring subscription for org {subscription.organization_id}")
            
            # Mark current subscription as expired
            subscription.status = PaymentStatus.EXPIRED
            subscription.updated_at = now
            
            # Only create Free plan if it's a paid plan that expired
            if subscription.plan_name != PlanName.FREE.value:
                # Create new Free plan subscription
                free_plan = session.exec(
                    select(PricingPlan).where(PricingPlan.name == PlanName.FREE.value)
                ).first()
                
                if free_plan:
                    new_subscription = Payment(
                        organization_id=subscription.organization_id,
                        user_id=subscription.user_id,
                        plan_name=PlanName.FREE.value,
                        pricing_plan_id=free_plan.id,
                        billing_cycle=BillingCycle.MONTHLY.value,
                        status=PaymentStatus.ACTIVE,
                        current_period_start=now,
                        current_period_end=now + timedelta(days=free_plan.duration_days),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(new_subscription)
            
            session.add(subscription)
        
        if expired_subs:
            session.commit()
            print(f"✅ Auto-expired {len(expired_subs)} subscriptions")
            
    except Exception as e:
        print(f"❌ Error in subscription expiry check: {e}")
        session.rollback()


def ensure_stripe_price_ids(plans: List[PricingPlan], session: Session) -> List[PricingPlan]:
    """Ensure all pricing plans have Stripe price IDs from environment variables"""
    needs_update = False
    
    for plan in plans:
        if plan.name == "Pro":
            current_id = plan.stripe_price_id_monthly
            correct_id = STRIPE_PRO_MONTHLY_PRICE_ID
            if current_id != correct_id or any(placeholder in str(current_id) for placeholder in ['YOUR_', 'placeholder']):
                print(f"🔄 Updating Pro plan price ID: {current_id} -> {correct_id}")
                plan.stripe_price_id_monthly = correct_id
                plan.stripe_price_id_yearly = correct_id
                needs_update = True
                
        elif plan.name == "Team":
            current_id = plan.stripe_price_id_monthly
            correct_id = STRIPE_TEAM_MONTHLY_PRICE_ID
            # ✅ FORCE UPDATE Team plan - check if it's using placeholder or wrong ID
            if (current_id != correct_id or 
                any(placeholder in str(current_id) for placeholder in ['YOUR_', 'placeholder']) or
                'YOUR_TEAM' in str(current_id)):
                print(f"🔄 FORCE UPDATING Team plan price ID: {current_id} -> {correct_id}")
                plan.stripe_price_id_monthly = correct_id
                plan.stripe_price_id_yearly = correct_id
                needs_update = True
                print(f"✅ Team plan price ID updated to: {correct_id}")
                
        elif plan.name == "Free":
            current_id = plan.stripe_price_id_monthly
            correct_id = STRIPE_FREE_PRICE_ID
            if current_id != correct_id or any(placeholder in str(current_id) for placeholder in ['YOUR_', 'placeholder']):
                print(f"🔄 Updating Free plan price ID: {current_id} -> {correct_id}")
                plan.stripe_price_id_monthly = correct_id
                plan.stripe_price_id_yearly = correct_id
                needs_update = True
    
    if needs_update:
        try:
            session.commit()
            print("✅ Successfully updated pricing plans with Stripe price IDs")
        except Exception as e:
            print(f"❌ Failed to update pricing plans: {e}")
            session.rollback()
            # Try to continue with existing plans even if update fails
    else:
        print("✅ All plans already have correct price IDs")
    
    return plans


def create_default_pricing_plans(session: Session):
    """Create default pricing plans with Stripe price IDs from environment"""
    default_plans = [
        {
            "name": "Free",
            "slug": "free",
            "max_invitations": 4,
            "price_monthly": 0.0,
            "price_yearly": 0.0,
            "description": "Perfect for small teams getting started",
            "is_active": True,
            "duration_days": 30,
            "stripe_price_id_monthly": STRIPE_FREE_PRICE_ID,
            "stripe_price_id_yearly": STRIPE_FREE_PRICE_ID,
        },
        {
            "name": "Pro", 
            "slug": "pro",
            "max_invitations": 11,
            "price_monthly": 29.0,
            "price_yearly": 29.0,  # Same as monthly since no yearly plan
            "description": "For growing teams with advanced needs",
            "is_active": True,
            "duration_days": 30,
            "stripe_price_id_monthly": STRIPE_PRO_MONTHLY_PRICE_ID,
            "stripe_price_id_yearly": STRIPE_PRO_MONTHLY_PRICE_ID,
        },
        {
            "name": "Team",
            "slug": "team", 
            "max_invitations": 9999,
            "price_monthly": 99.0,
            "price_yearly": 99.0,  # Same as monthly since no yearly plan
            "description": "For large organizations and enterprises",
            "is_active": True,
            "duration_days": 30,
            "stripe_price_id_monthly": STRIPE_TEAM_MONTHLY_PRICE_ID,
            "stripe_price_id_yearly": STRIPE_TEAM_MONTHLY_PRICE_ID,
        }
    ]
    
    created_plans = []
    for plan_data in default_plans:
        plan = PricingPlan(**plan_data)
        session.add(plan)
        created_plans.append(plan)
    
    session.commit()
    
    # Refresh to get IDs
    for plan in created_plans:
        session.refresh(plan)
    
    print("✅ Created default pricing plans with Stripe price IDs")
    return created_plans


def get_fallback_plans():
    """Return fallback plans if database is unavailable"""
    return [
        PlanOut(
            id=1,
            name="Free",
            slug="free",
            member_limit=3,
            description="Perfect for small teams getting started",
            features=get_plan_features(PlanName.FREE),
            price_monthly=0.0,
            price_yearly=0.0,
            stripe_price_id_monthly=STRIPE_FREE_PRICE_ID,
            stripe_price_id_yearly=STRIPE_FREE_PRICE_ID,
        ),
        PlanOut(
            id=2,
            name="Pro",
            slug="pro",
            member_limit=10,
            description="For growing teams with advanced needs",
            features=get_plan_features(PlanName.PRO),
            price_monthly=29.0,
            price_yearly=29.0,
            stripe_price_id_monthly=STRIPE_PRO_MONTHLY_PRICE_ID,
            stripe_price_id_yearly=STRIPE_PRO_MONTHLY_PRICE_ID,
        ),
        PlanOut(
            id=3,
            name="Team",
            slug="team",
            member_limit=9999,
            description="For large organizations and enterprises",
            features=get_plan_features(PlanName.TEAM),
            price_monthly=99.0,
            price_yearly=99.0,
            stripe_price_id_monthly=STRIPE_TEAM_MONTHLY_PRICE_ID,
            stripe_price_id_yearly=STRIPE_TEAM_MONTHLY_PRICE_ID,
        )
    ]


# -------------------------
# Background Task Setup
# -------------------------
@router.on_event("startup")
async def startup_subscription_check():
    """Start background task to check subscription expiry"""
    async def run_periodic_check():
        while True:
            try:
                with next(get_session()) as session:
                    await check_and_expire_subscriptions(session)
            except Exception as e:
                print(f"Background task error: {e}")
            await asyncio.sleep(3600)  # Check every hour
    
    asyncio.create_task(run_periodic_check())


# -------------------------
# Routes
# -------------------------
@router.get("/visibility", response_model=VisibilityResponse)
def payment_visibility(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Return whether the current user should see payment features."""
    role = current_user.role
    is_invited = current_user.is_invited
    is_public_admin = current_user.is_public_admin
    
    is_public_super_admin = (role == UserRole.SUPER_ADMIN.value and is_public_admin)
    org = session.get(Organization, current_user.organization_id)
    is_tenant_owner = (org and org.super_admin_id == current_user.id)
    
    show_payment = is_public_super_admin and is_tenant_owner
    
    return VisibilityResponse(
        show_payment=show_payment,
        user_role=role,
        is_super_admin=is_public_super_admin,
        is_invited=is_invited
    )





def debug_plan_prices(plans: List[PricingPlan]):
    """Debug function to log current plan price IDs"""
    print("🔍 DEBUG - Current Plan Price IDs:")
    for plan in plans:
        print(f"   - {plan.name}: {plan.stripe_price_id_monthly}")
    
    print("🔍 DEBUG - Environment Price IDs:")
    print(f"   - Pro: {STRIPE_PRO_MONTHLY_PRICE_ID}")
    print(f"   - Team: {STRIPE_TEAM_MONTHLY_PRICE_ID}")
    print(f"   - Free: {STRIPE_FREE_PRICE_ID}")




@router.get("/plans", response_model=List[PlanOut])
def list_plans(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    List available pricing plans from database.
    """
    try:
        statement = select(PricingPlan).where(PricingPlan.is_active == True)
        plans = session.exec(statement).all()
        
        print(f"📦 Found {len(plans)} active pricing plans")
        
        # ✅ ADD DEBUG LOGGING BEFORE UPDATE
        print("🔍 DEBUG - Current Plan Price IDs (BEFORE update):")
        for plan in plans:
            print(f"   - {plan.name}: {plan.stripe_price_id_monthly}")
        
        print("🔍 DEBUG - Environment Price IDs:")
        print(f"   - Pro: {STRIPE_PRO_MONTHLY_PRICE_ID}")
        print(f"   - Team: {STRIPE_TEAM_MONTHLY_PRICE_ID}")
        print(f"   - Free: {STRIPE_FREE_PRICE_ID}")
        
        if not plans:
            print("⚠️ No active plans found in database, creating default plans...")
            plans = create_default_pricing_plans(session)
        else:
            # ✅ Ensure all plans have proper Stripe price IDs
            plans = ensure_stripe_price_ids(plans, session)
            
            # ✅ ADD DEBUG LOGGING AFTER UPDATE
            print("🔍 DEBUG - Current Plan Price IDs (AFTER update):")
            for plan in plans:
                print(f"   - {plan.name}: {plan.stripe_price_id_monthly}")
        
        plan_out_list = []
        for plan in plans:
            # ✅ ADD VALIDATION FOR EACH PLAN
            is_valid_price_id = (
                plan.stripe_price_id_monthly and 
                plan.stripe_price_id_monthly.startswith('price_') and
                not any(placeholder in plan.stripe_price_id_monthly for placeholder in ['YOUR_', 'placeholder'])
            )
            
            if not is_valid_price_id and plan.name != "Free":
                print(f"⚠️ WARNING: Plan {plan.name} has invalid price ID: {plan.stripe_price_id_monthly}")
            
            plan_out_list.append(PlanOut(
                id=plan.id,
                name=plan.name,
                slug=plan.slug or plan.name.lower(),
                member_limit=plan.max_invitations,
                description=plan.description,
                features=get_plan_features(plan.name),
                price_monthly=plan.price_monthly,
                price_yearly=plan.price_yearly,
                stripe_price_id_monthly=plan.stripe_price_id_monthly,
                stripe_price_id_yearly=plan.stripe_price_id_yearly
            ))
        
        print(f"✅ Returning {len(plan_out_list)} plans to frontend")
        return plan_out_list
        
    except Exception as e:
        print(f"❌ Error in list_plans: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return get_fallback_plans()
    


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(
    payload: CheckoutSessionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_public_super_admin),
    session: Session = Depends(get_session),
):
    """Create Stripe Checkout Session for subscription payment"""
    payment = None
    
    try:
        price_id = payload.price_id
        
        if not price_id:
            raise HTTPException(status_code=400, detail="Price ID is required")

        print(f"🎯 Starting checkout session creation")
        print(f"💰 Price ID: {price_id}")
        print(f"👤 User ID: {current_user.id}, Org ID: {current_user.organization_id}")

        # ✅ VALIDATE: Check if this is a known Stripe price ID
        valid_price_ids = [STRIPE_PRO_MONTHLY_PRICE_ID, STRIPE_TEAM_MONTHLY_PRICE_ID, STRIPE_FREE_PRICE_ID]
        if price_id not in valid_price_ids:
            print(f"❌ Invalid price ID requested: {price_id}")
            raise HTTPException(status_code=400, detail="Invalid price ID")

        # Find the pricing plan
        statement = select(PricingPlan).where(
            (PricingPlan.stripe_price_id_monthly == price_id) |
            (PricingPlan.stripe_price_id_yearly == price_id)
        )
        pricing_plan = session.exec(statement).first()
        
        if not pricing_plan:
            print(f"❌ Pricing plan not found for price ID: {price_id}")
            raise HTTPException(status_code=404, detail="Pricing plan not found")

        print(f"📋 Found pricing plan: {pricing_plan.name}")

        # ✅ VALIDATE: Check if Stripe price ID exists
        try:
            price_obj = stripe.Price.retrieve(price_id)
            print(f"✅ Valid Stripe price ID: {price_id}")
            print(f"💲 Price details: {price_obj.unit_amount/100} {price_obj.currency.upper()}")
        except Exception as e:
            print(f"❌ Invalid Stripe price ID: {price_id} - {e}")
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid price configuration for {pricing_plan.name} plan. Please contact support."
            )

        # ENFORCEMENT: Check member limits before allowing upgrade
        try:
            enforce_plan_limits(current_user.organization_id, session)
            print("✅ Member limits check passed")
        except HTTPException as e:
            print(f"⚠️ Member limit warning: {e.detail}")

        # Cancel any existing active subscription
        existing_sub = get_current_subscription_for_org(current_user.organization_id, session)
        if existing_sub:
            print(f"🔄 Canceling existing subscription: {existing_sub.id}")
            # ✅ FIXED: Use CANCELLED (double L)
            existing_sub.status = PaymentStatus.CANCELLED
            existing_sub.updated_at = datetime.utcnow()
            session.add(existing_sub)
        else:
            print("ℹ️ No existing subscription found")

        # Determine billing cycle (all monthly for now)
        billing_cycle = BillingCycle.MONTHLY
        print(f"💳 Billing cycle: {billing_cycle.value}")

        # Create pending payment record
        now = datetime.utcnow()
        period_end = now + timedelta(days=pricing_plan.duration_days)
        
        payment = Payment(
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            plan_name=pricing_plan.name,
            pricing_plan_id=pricing_plan.id,
            billing_cycle=billing_cycle.value,
            stripe_price_id=price_id,
            status=PaymentStatus.PENDING,
            current_period_start=now,
            current_period_end=period_end,
            created_at=now,
            updated_at=now,
        )

        session.add(payment)
        session.commit()
        session.refresh(payment)
        print(f"💾 Created payment record: {payment.id}")

        # Create Stripe checkout session - FIXED TIMESTAMP
        try:
            # ✅ FIX: Use proper timestamp calculation
            import time
            expires_at = int(time.time()) + 3600  # 1 hour from now in seconds
            

            # checkout_session = stripe.checkout.Session.create(
            #     payment_method_types=['card'],
            #     line_items=[{
            #         'price': price_id, 
            #         'quantity': 1
            #     }],
            #     mode='subscription',
            #     success_url=f"http://localhost:5173/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            #     cancel_url="http://localhost:5173/payment/cancel",
            #     client_reference_id=str(payment.id),
            #     customer_email=current_user.email,

            #     metadata={
            #         'payment_id': str(payment.id),
            #         'user_id': str(current_user.id),
            #         'organization_id': str(current_user.organization_id),
            #         'plan_name': pricing_plan.name,
            #         'billing_cycle': billing_cycle.value
            #     },

            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1
                }],
                mode='subscription',
                success_url=settings.STRIPE_SUCCESS_URL,
                cancel_url=settings.STRIPE_CANCEL_URL,
                client_reference_id=str(payment.id),
                customer_email=current_user.email,
                metadata={
                    'payment_id': str(payment.id),
                    'user_id': str(current_user.id),
                    'organization_id': str(current_user.organization_id),
                    'plan_name': pricing_plan.name,
                    'billing_cycle': billing_cycle.value
                },

                locale='auto',
                billing_address_collection='required',
                allow_promotion_codes=True,
                subscription_data={
                    'metadata': {
                        'payment_id': str(payment.id),
                        'user_id': str(current_user.id),
                        'organization_id': str(current_user.organization_id)
                    }
                },
                expires_at=expires_at,  # ✅ FIXED: Proper Unix timestamp
            )
            
            print(f"✅ Stripe checkout session created successfully!")
            print(f"   - Session ID: {checkout_session.id}")
            print(f"   - Plan: {pricing_plan.name}")
            print(f"   - Checkout URL: {checkout_session.url}")
            print(f"   - Expires at: {expires_at} (Unix timestamp)")
            
            return CheckoutSessionResponse(
                checkout_url=checkout_session.url,
                session_id=checkout_session.id
            )
            
        except Exception as stripe_error:
            print(f"❌ Stripe session creation failed: {stripe_error}")
            if payment:
                # ✅ FIXED: Use CANCELLED (double L)
                payment.status = PaymentStatus.CANCELLED
                session.commit()
            raise
        
    # ✅ FIXED: Use proper exception handling for Stripe
    except stripe._error.InvalidRequestError as e:  # Use internal _error
        print(f"❌ Stripe invalid request error: {e}")
        if payment:
            # ✅ FIXED: Use CANCELLED (double L)
            payment.status = PaymentStatus.CANCELLED
            payment.updated_at = datetime.utcnow()
            session.commit()
        
        error_msg = str(e)
        if "No such price" in error_msg:
            error_msg = "Payment configuration error for this plan. Please contact support."
        elif "expires_at" in error_msg:
            error_msg = "Payment session configuration error. Please try again."
            
        raise HTTPException(status_code=400, detail=error_msg)
        
    except Exception as e:
        print(f"❌ Stripe API error: {e}")
        if payment:
            # ✅ FIXED: Use CANCELLED (double L)
            payment.status = PaymentStatus.CANCELLED
            payment.updated_at = datetime.utcnow()
            session.commit()
        
        # Handle various Stripe error types
        error_msg = str(e)
        if "InvalidRequestError" in str(type(e)):
            raise HTTPException(status_code=400, detail=f"Payment configuration error: {error_msg}")
        else:
            raise HTTPException(status_code=400, detail=f"Payment service error: {error_msg}")
        
    except HTTPException:
        raise
        
    except Exception as e:
        print(f"❌ Unexpected error in create-checkout-session: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        
        if payment:
            # ✅ FIXED: Use CANCELLED (double L)
            payment.status = PaymentStatus.CANCELLED
            payment.updated_at = datetime.utcnow()
            session.commit()
            
        raise HTTPException(
            status_code=500, 
            detail="An unexpected error occurred while creating payment session. Please try again or contact support."
        )
    
    

@router.post("/subscribe-free")
def subscribe_free_plan(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_public_super_admin),
    session: Session = Depends(get_session),
):
    """Subscribe to free plan (no Stripe payment required)"""
    org_id = current_user.organization_id
    if org_id is None:
        raise HTTPException(
            status_code=400,
            detail="🚫 User does not belong to an organization"
        )

    # ✅ Check current subscription
    current_subscription = get_current_subscription_for_org(org_id, session)

    # ✅ Enforce member limits before switching to Free plan
    members_count = session.query(User).filter(User.organization_id == org_id).count()
    if members_count > 3:
        raise HTTPException(
            status_code=400,
            detail=f"🚫 Cannot switch to Free plan\n\nYou currently have {members_count} team members, but the Free plan allows maximum 3 members.\n\nPlease remove extra members first or upgrade to a higher plan."
        )

    # ✅ If switching from paid to free, ensure limits are still enforced
    if current_subscription and current_subscription.plan_name != PlanName.FREE.value:
        try:
            enforce_plan_limits(org_id, session)
        except HTTPException as e:
            raise HTTPException(
                status_code=403,
                detail=f"🚫 Cannot switch to Free plan\n\n{e.detail}\n\nPlease remove some members first or upgrade to a higher plan."
            )

    # ✅ Cancel any existing active subscription
    if current_subscription:
        current_subscription.status = PaymentStatus.CANCELLED
        current_subscription.updated_at = datetime.utcnow()
        session.add(current_subscription)

    # ✅ Find or create the Free plan in PricingPlan table
    free_plan = session.exec(
        select(PricingPlan).where(
            (PricingPlan.name == PlanName.FREE.value) |
            (PricingPlan.name == "Free")
        )
    ).first()

    if not free_plan:
        free_plan = PricingPlan(
            name="Free",
            slug="free",
            max_invitations=4,
            price_monthly=0.0,
            price_yearly=0.0,
            description="Perfect for small teams getting started",
            is_active=True,
            duration_days=30,
            stripe_price_id_monthly=STRIPE_FREE_PRICE_ID,
            stripe_price_id_yearly=STRIPE_FREE_PRICE_ID,
        )
        session.add(free_plan)
        session.commit()
        session.refresh(free_plan)

    # ✅ Create a new active Payment record for Free plan
    now = datetime.utcnow()
    payment = Payment(
        organization_id=org_id,
        user_id=current_user.id,
        plan_name=PlanName.FREE.value,
        pricing_plan_id=free_plan.id,
        billing_cycle=BillingCycle.MONTHLY.value,
        status=PaymentStatus.ACTIVE,
        current_period_start=now,
        current_period_end=now + timedelta(days=free_plan.duration_days),
        created_at=now,
        updated_at=now,
    )

    session.add(payment)
    session.commit()
    session.refresh(payment)

    # ✅ Link this payment record to organization
    org = session.get(Organization, org_id)
    if org:
        org.current_payment_id = payment.id
        session.add(org)
        session.commit()

    # ✅ Run background expiry check
    background_tasks.add_task(check_and_expire_subscriptions, session)

    # ✅ Return consistent API response
    return {
        "detail": "✅ Successfully switched to Free plan!\n\nNote: You can invite up to 3 team members with the Free plan.",
        "subscription": ActiveSubscriptionOut(
            id=payment.id,
            organization_id=payment.organization_id,
            user_id=payment.user_id,
            plan_name=payment.plan_name,
            pricing_plan_id=payment.pricing_plan_id,
            stripe_subscription_id=payment.stripe_subscription_id,
            status=payment.status,
            start_date=payment.current_period_start,
            end_date=payment.current_period_end,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )
    }


@router.post("/cancel", status_code=status.HTTP_200_OK)
def cancel_subscription(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_public_super_admin),
):
    """Cancel the active subscription for the current user's organization."""
    org_id = current_user.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="User does not belong to an organization")

    payment = get_current_subscription_for_org(org_id, session)
    if not payment:
        raise HTTPException(status_code=404, detail="No active subscription found")

    # If it's a paid plan with Stripe subscription, cancel it via Stripe
    if payment.stripe_subscription_id and payment.plan_name != PlanName.FREE.value:
        try:
            stripe.Subscription.delete(payment.stripe_subscription_id)
        except Exception as e:
            print(f"Stripe cancellation failed: {e}")

    payment.status = PaymentStatus.CANCELLED
    org = session.get(Organization, payment.organization_id)
    if org:
        org.current_payment_id = None
        session.add(org)
        session.commit()

    payment.end_date = datetime.utcnow()
    payment.updated_at = datetime.utcnow()

    session.add(payment)
    session.commit()

    # Auto-subscribe to Free plan after cancellation
    background_tasks.add_task(subscribe_free_plan, current_user, session)

    return {
        "detail": "Subscription canceled successfully",
        "subscription_id": payment.id,
        "status": payment.status
    }


@router.get("/current", response_model=Optional[ActiveSubscriptionOut])
def get_current_subscription(
    session: Session = Depends(get_session),
    _: bool = Depends(verify_payment_access),
    current_user: User = Depends(get_current_user),
):
    """Return the currently active subscription for the user's organization."""
    org_id = current_user.organization_id
    if org_id is None:
        return None

    payment = get_current_subscription_for_org(org_id, session)
    if not payment:
        return None

    # Check if subscription is expired (real-time check)
    if payment.current_period_end < datetime.utcnow():
        payment.status = PaymentStatus.EXPIRED
        session.add(payment)
        session.commit()
        return None

    return ActiveSubscriptionOut(
        id=payment.id,
        organization_id=payment.organization_id,
        user_id=payment.user_id,
        plan_name=payment.plan_name,
        pricing_plan_id=payment.pricing_plan_id,
        stripe_subscription_id=payment.stripe_subscription_id,
        status=payment.status,
        start_date=payment.current_period_start,
        end_date=payment.current_period_end,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )












@router.get("/history", response_model=List[PaymentHistoryOut])
def get_payment_history(
    session: Session = Depends(get_session),
    _: bool = Depends(verify_payment_access),
    current_user: User = Depends(get_current_user),
):
    """Get payment history for the organization."""
    org_id = current_user.organization_id
    if org_id is None:
        return []

    statement = (
        select(Payment)
        .where(Payment.organization_id == org_id)
        .order_by(Payment.created_at.desc())
    )
    payments = session.exec(statement).all()
    
    return [
        PaymentHistoryOut(
            id=payment.id,
            plan_name=payment.plan_name,
            pricing_plan_id=payment.pricing_plan_id,
            status=payment.status,
            start_date=payment.current_period_start,
            end_date=payment.current_period_end,
            created_at=payment.created_at,
        )
        for payment in payments
    ]


@router.get("/check-limits")
def check_plan_limits(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Check current plan limits and usage"""
    org_id = current_user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User does not belong to an organization")

    subscription = get_current_subscription_for_org(org_id, session)
    current_members = get_organization_member_count(org_id, session)
    
    if subscription:
        plan_limit = get_plan_member_limit(subscription.plan_name)
        is_expired = subscription.current_period_end < datetime.utcnow()
    else:
        plan_limit = 3  # Free plan limit
        is_expired = False

    return {
        "current_plan": subscription.plan_name if subscription else "Free",
        "current_members": current_members,
        "member_limit": plan_limit,
        "can_add_more": current_members < plan_limit and not is_expired,
        "is_expired": is_expired,
        "remaining_slots": max(0, plan_limit - current_members) if not is_expired else 0
    }


@router.get("/verify-session")
def verify_stripe_session(session_id: str, session: Session = Depends(get_session)):
    """Public endpoint to verify Stripe session status - no auth required"""
    try:
        # Retrieve session from Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        # Get payment record using client_reference_id (which is our payment ID)
        payment_id = stripe_session.get('client_reference_id')
        if not payment_id:
            return {"status": "unknown", "message": "No payment reference found"}
        
        payment = session.get(Payment, int(payment_id))
        if not payment:
            return {"status": "unknown", "message": "Payment record not found"}
        
        return {
            "status": stripe_session.status,
            "payment_status": stripe_session.payment_status,
            "subscription_id": stripe_session.subscription,
            "customer_email": stripe_session.customer_details.email if stripe_session.customer_details else None,
            "plan_name": payment.plan_name,
            "amount_total": stripe_session.amount_total,  # in cents
            "currency": stripe_session.currency
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error verifying session: {str(e)}")


@router.post("/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    """Handle Stripe webhook events for subscription updates"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        print("❌ STRIPE_WEBHOOK_SECRET not configured")
        return JSONResponse(
            status_code=500, 
            content={"error": "Webhook secret not configured"}
        )

    if not sig_header:
        print("❌ Missing stripe-signature header")
        return JSONResponse(
            status_code=400, 
            content={"error": "Missing stripe-signature header"}
        )

    try:
        # Construct event with proper error handling
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret
        )
        print(f"✅ Webhook received: {event['type']}")

    except ValueError as e:
        # Invalid payload
        print(f"❌ Invalid payload: {e}")
        return JSONResponse(
            status_code=400, 
            content={"error": "Invalid payload"}
        )
    except stripe.SignatureVerificationError as e:
        # Invalid signature - use the correct exception
        print(f"❌ Invalid signature: {e}")
        return JSONResponse(
            status_code=400, 
            content={"error": "Invalid signature"}
        )
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return JSONResponse(
            status_code=400, 
            content={"error": f"Webhook error: {str(e)}"}
        )

    # Process the event
    event_type = event['type']
    data_object = event['data']['object']

    try:
        if event_type == "checkout.session.completed":
            await handle_checkout_session_completed(data_object, session)
        elif event_type == "invoice.payment_succeeded":
            await handle_invoice_payment_succeeded(data_object, session)
        elif event_type == "invoice.payment_failed":
            await handle_invoice_payment_failed(data_object, session)
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(data_object, session)
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(data_object, session)
        else:
            print(f"ℹ️ Unhandled event type: {event_type}")

        return JSONResponse(
            status_code=200, 
            content={"status": "success", "event": event_type}
        )

    except Exception as e:
        print(f"❌ Error processing webhook event {event_type}: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500, 
            content={"error": f"Error processing event: {str(e)}"}
        )


async def handle_checkout_session_completed(session_data, db_session: Session):
    """Handle successful checkout session completion"""
    try:
        payment_id = session_data.get('client_reference_id')
        if not payment_id:
            print("❌ No client_reference_id in session")
            return

        payment = db_session.get(Payment, int(payment_id))
        if not payment:
            print(f"❌ Payment not found: {payment_id}")
            return

        # Update payment status
        payment.status = PaymentStatus.ACTIVE
        # Link payment to organization
        org = db_session.get(Organization, payment.organization_id)
        if org:
            org.current_payment_id = payment.id
            db_session.add(org)
            db_session.commit()

        payment.stripe_subscription_id = session_data.get('subscription')
        payment.stripe_customer_id = session_data.get('customer')
        payment.updated_at = datetime.utcnow()
        
        # Set proper period dates
        now = datetime.utcnow()
        payment.current_period_start = now
        
        # Get subscription details from Stripe for accurate dates
        if session_data.get('subscription'):
            try:
                subscription = stripe.Subscription.retrieve(session_data['subscription'])
                payment.current_period_end = datetime.fromtimestamp(subscription.current_period_end)
                print(f"📅 Subscription period from Stripe: {payment.current_period_end}")
            except Exception as e:
                print(f"⚠️ Could not get subscription dates, using default: {e}")
                payment.current_period_end = now + timedelta(days=30)
        else:
            payment.current_period_end = now + timedelta(days=30)
        
        db_session.add(payment)
        db_session.commit()
        print(f"✅ Payment {payment.id} activated for org {payment.organization_id}")
        
    except Exception as e:
        print(f"❌ Error in handle_checkout_session_completed: {e}")
        db_session.rollback()
        raise

# Update all other handler functions to be async as well
async def handle_invoice_payment_succeeded(invoice, db_session: Session):
    """Handle successful invoice payment"""
    try:
        subscription_id = invoice.get('subscription')
        if not subscription_id:
            return

        statement = select(Payment).where(Payment.stripe_subscription_id == subscription_id)
        payment = db_session.exec(statement).first()
        
        if payment:
            payment.current_period_start = datetime.fromtimestamp(invoice['period_start'])
            payment.current_period_end = datetime.fromtimestamp(invoice['period_end'])
            payment.updated_at = datetime.utcnow()
            db_session.add(payment)
            db_session.commit()
            print(f"✅ Updated payment periods for subscription {subscription_id}")
            
    except Exception as e:
        print(f"❌ Error in handle_invoice_payment_succeeded: {e}")
        db_session.rollback()

async def handle_invoice_payment_failed(invoice, db_session: Session):
    """Handle failed invoice payment"""
    try:
        subscription_id = invoice.get('subscription')
        if not subscription_id:
            return

        statement = select(Payment).where(Payment.stripe_subscription_id == subscription_id)
        payment = db_session.exec(statement).first()
        
        if payment and payment.plan_name != PlanName.FREE.value:
            payment.status = PaymentStatus.PAST_DUE
            payment.updated_at = datetime.utcnow()
            db_session.add(payment)
            db_session.commit()
            print(f"⚠️ Payment failed for subscription {subscription_id}")
            
    except Exception as e:
        print(f"❌ Error in handle_invoice_payment_failed: {e}")
        db_session.rollback()

async def handle_subscription_updated(subscription, db_session: Session):
    """Handle subscription updates"""
    try:
        subscription_id = subscription['id']
        
        statement = select(Payment).where(Payment.stripe_subscription_id == subscription_id)
        payment = db_session.exec(statement).first()
        
        if payment:
            payment.current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
            payment.current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
            payment.updated_at = datetime.utcnow()
            db_session.add(payment)
            db_session.commit()
            print(f"✅ Updated subscription {subscription_id}")
            
    except Exception as e:
        print(f"❌ Error in handle_subscription_updated: {e}")
        db_session.rollback()

async def handle_subscription_deleted(subscription, db_session: Session):
    """Handle subscription deletion"""
    try:
        subscription_id = subscription['id']
        
        statement = select(Payment).where(Payment.stripe_subscription_id == subscription_id)
        payment = db_session.exec(statement).first()
        
        if payment and payment.plan_name != PlanName.FREE.value:
            payment.status = PaymentStatus.CANCELLED
            payment.end_date = datetime.utcnow()
            payment.updated_at = datetime.utcnow()
            db_session.add(payment)
            db_session.commit()
            print(f"🗑️ Subscription {subscription_id} canceled")
            
    except Exception as e:
        print(f"❌ Error in handle_subscription_deleted: {e}")
        db_session.rollback()







@router.post("/fix-team-plan-price")
def fix_team_plan_price(session: Session = Depends(get_session)):
    """Temporary route to fix Team plan price ID"""
    try:
        team_plan = session.exec(
            select(PricingPlan).where(PricingPlan.name == "Team")
        ).first()
        
        if team_plan:
            print(f"🔄 Fixing Team plan price ID:")
            print(f"   Before: {team_plan.stripe_price_id_monthly}")
            team_plan.stripe_price_id_monthly = STRIPE_TEAM_MONTHLY_PRICE_ID
            team_plan.stripe_price_id_yearly = STRIPE_TEAM_MONTHLY_PRICE_ID
            session.add(team_plan)
            session.commit()
            session.refresh(team_plan)
            print(f"   After: {team_plan.stripe_price_id_monthly}")
            return {"status": "fixed", "new_price_id": team_plan.stripe_price_id_monthly}
        else:
            return {"status": "not_found"}
            
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error fixing team plan: {e}")
    







# Add this route to your payment.py router
@router.get("/me/subscription")
def get_user_subscription(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get current user's active subscription with expiry info"""
    try:
        # Get current active subscription for user's organization
        org_id = current_user.organization_id
        if not org_id:
            return {
                "plan_id": "free",
                "start_at": None,
                "expires_at": None,
                "status": "inactive",
                "days_left": 0
            }

        subscription = get_current_subscription_for_org(org_id, session)
        
        if not subscription:
            return {
                "plan_id": "free",
                "start_at": None,
                "expires_at": None,
                "status": "inactive", 
                "days_left": 0
            }

        now = datetime.utcnow()
        expires_at = subscription.current_period_end
        days_left = max(0, (expires_at - now).days) if expires_at else 0
        
        # Determine status based on expiry
        if subscription.status == PaymentStatus.ACTIVE and expires_at > now:
            status = "active"
        elif subscription.status == PaymentStatus.ACTIVE and expires_at <= now:
            status = "expired"
        else:
            status = subscription.status.lower()

        return {
            "plan_id": subscription.plan_name.lower(),
            "start_at": subscription.current_period_start.isoformat() + "Z",
            "expires_at": expires_at.isoformat() + "Z" if expires_at else None,
            "status": status,
            "days_left": days_left
        }

    except Exception as e:
        print(f"Error getting user subscription: {e}")
        return {
            "plan_id": "free",
            "start_at": None,
            "expires_at": None,
            "status": "error",
            "days_left": 0
        }
    
