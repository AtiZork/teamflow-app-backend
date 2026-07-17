# routes/organization.py
from fastapi import APIRouter, HTTPException, Depends, status
from sqlmodel import Session, select
from typing import List
from core.database import get_session
from core.security import get_current_user, get_current_admin
from models.models import User, Organization
from schemas.organization_schema import OrganizationRead, OrganizationUpdate
from schemas.user_schema import UserRead

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def _require_same_org(current_user: User, organization_id: int) -> None:
    if current_user.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this organization",
        )


# ==================================================================
#  ✅ GET MY ORGANIZATION
# ==================================================================
@router.get("/my-organization", response_model=OrganizationRead)
def get_my_organization(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
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
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    """Update current user's organization"""
    organization = session.get(Organization, current_user.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    if organization_update.name is not None:
        organization.name = organization_update.name
    if organization_update.slug is not None:
        organization.slug = organization_update.slug

    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization


# ==================================================================
#  ✅ GET ORGANIZATIONS (tenant-scoped)
# ==================================================================
@router.get("/", response_model=List[OrganizationRead])
def get_all_organizations(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    """Get organizations visible to the current admin (own org only)."""
    organization = session.get(Organization, current_user.organization_id)
    if not organization:
        return []
    return [organization]


# ==================================================================
#  ✅ GET ORGANIZATION MEMBERS
# ==================================================================
@router.get("/{organization_id}/members", response_model=List[UserRead])
def get_organization_members(
    organization_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List active members of an organization (same-tenant only)."""
    _require_same_org(current_user, organization_id)
    members = session.exec(
        select(User).where(
            User.organization_id == organization_id,
            User.is_active == True,
        )
    ).all()
    return members


# ==================================================================
#  ✅ GET ORGANIZATION BY ID
# ==================================================================
@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Get a specific organization (same-tenant only)."""
    _require_same_org(current_user, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization
