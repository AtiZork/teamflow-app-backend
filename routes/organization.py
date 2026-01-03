# routes/organization.py
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from core.database import get_session
from core.security import get_current_user, get_current_admin
from models.models import User, Organization
from schemas.organization_schema import OrganizationRead, OrganizationCreate, OrganizationUpdate

router = APIRouter(prefix="/organizations", tags=["Organizations"])


# ==================================================================
#  ✅ GET MY ORGANIZATION
# ================================================================== 
@router.get("/my-organization", response_model=OrganizationRead)
def get_my_organization(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get current user's organization"""
    organization = session.get(Organization, current_user.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization

# ==================================================================
#  ✅ UPDATE MY ORGANIZATION
# ================================================================== 
@router.put("/my-organization", response_model=OrganizationRead)
def update_my_organization(
    organization_update: OrganizationUpdate,
    current_user: User = Depends(get_current_admin),  # Only admins can update org
    session: Session = Depends(get_session)
):
    """Update current user's organization"""
    organization = session.get(Organization, current_user.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # Update organization fields
    if organization_update.name is not None:
        organization.name = organization_update.name
    if organization_update.slug is not None:
        organization.slug = organization_update.slug
    
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization

# ==================================================================
#  ✅ GET ALL ORGANIZATION
# ================================================================== 
@router.get("/", response_model=List[OrganizationRead])
def get_all_organizations(
    current_user: User = Depends(get_current_admin),  # Only admins can see all orgs
    session: Session = Depends(get_session)
):
    """Get all organizations (admin only)"""
    organizations = session.exec(select(Organization)).all()
    return organizations

# ==================================================================
#  ✅ GET ORGANIZATION
# ================================================================== 
@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: int,
    current_user: User = Depends(get_current_admin),  # Only admins can see specific orgs
    session: Session = Depends(get_session)
):
    """Get a specific organization (admin only)"""
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization





# In your organization creation/signup logic
from datetime import datetime, timedelta
from models.models import Payment, PricingPlan, PlanName, PaymentStatus, BillingCycle

def create_organization_with_free_plan(org_name: str, user: User, session: Session):
    """Create organization and automatically activate Free plan"""
    
    # 1. Create organization
    organization = Organization(
        name=org_name,
        super_admin_id=user.id,
        created_at=datetime.utcnow()
    )
    session.add(organization)
    session.flush()  # Get organization ID
    
    # 2. Assign user to organization
    user.organization_id = organization.id
    session.add(user)
    
    # 3. Find or create Free pricing plan
    free_plan = session.exec(
        select(PricingPlan).where(PricingPlan.name == PlanName.FREE.value)
    ).first()
    
    if not free_plan:
        # Create Free plan if it doesn't exist
        free_plan = PricingPlan(
            name=PlanName.FREE.value,
            slug="free",
            max_invitations=4,
            price_monthly=0.0,
            price_yearly=0.0,
            description="Perfect for small teams getting started",
            is_active=True,
            duration_days=30,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(free_plan)
        session.flush()
    
    # 4. Auto-activate Free plan subscription
    now = datetime.utcnow()
    free_payment = Payment(
        organization_id=organization.id,
        user_id=user.id,
        plan_name=PlanName.FREE.value,
        pricing_plan_id=free_plan.id,
        status=PaymentStatus.ACTIVE,
        billing_cycle=BillingCycle.MONTHLY.value,
        current_period_start=now,
        current_period_end=now + timedelta(days=free_plan.duration_days),
        created_at=now,
        updated_at=now,
    )
    session.add(free_payment)
    
    session.commit()
    return organization