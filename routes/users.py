# routes/users.py
from fastapi import APIRouter, HTTPException, Depends, status
from sqlmodel import Session, select
from typing import List
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models.models import User, UserRole
from schemas.user_schema import UserCreate, UserRead, UserUpdate
from core.database import get_session
from core.security import get_current_user, get_current_admin

import logging
logger = logging.getLogger(__name__)


router = APIRouter(tags=["Users"])


# ================================================================
# ✅ Get Current User
# ================================================================
@router.get("/me", response_model=UserRead)
def get_current_user_endpoint(current_user: User = Depends(get_current_user)):
    """Return current user info (decoded from JWT)."""
    return current_user


# ================================================================
# ✅ Update Current User Profile (Self)
# ================================================================
@router.put("/me", response_model=UserRead)
def update_current_user_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Allow a user to update their own profile (within org scope)."""

    # Scoped email uniqueness check
    if user_update.email and user_update.email != current_user.email:
        existing_user = session.exec(
            select(User).where(
                User.email == user_update.email,
                User.organization_id == current_user.organization_id
            )
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered in this organization."
            )
        current_user.email = user_update.email

    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name

    # Only admins/super admins can modify role or active status
    if user_update.role is not None:
        if current_user.role not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to change user roles."
            )
        current_user.role = user_update.role

    if user_update.is_active is not None:
        if current_user.role not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to change active status."
            )
        current_user.is_active = user_update.is_active

    # Handle profile fields
    if user_update.department is not None:
        current_user.department = user_update.department
    if user_update.job_title is not None:
        current_user.job_title = user_update.job_title
    if user_update.phone_number is not None:
        current_user.phone_number = user_update.phone_number
    if user_update.time_zone is not None:
        current_user.time_zone = user_update.time_zone
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    if user_update.skills is not None:
        current_user.skills = user_update.skills
    if user_update.profile_picture is not None:
        current_user.profile_picture = user_update.profile_picture

    try:
        session.add(current_user)
        session.commit()
        session.refresh(current_user)
        return current_user
    except IntegrityError as e:
        session.rollback()
        error_msg = str(e.orig)
        if "uq_org_email" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered in this organization."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A database constraint was violated."
            )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while updating your profile."
        )


# ================================================================
# ✅ Get All Users (Organization-Scoped, Admin only)
# ================================================================
@router.get("/", response_model=List[UserRead])
def get_all_users(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Admins: list all users in your organization."""
    users = session.exec(
        select(User).where(User.organization_id == current_user.organization_id)
    ).all()
    return users


# ================================================================
# ✅ Get User by ID (Org-Scoped)
# ================================================================
@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Retrieve a user by ID (must be in the same organization)."""
    user = session.exec(
        select(User)
        .where(User.id == user_id, User.organization_id == current_user.organization_id)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Members can only see their own profile
    if current_user.role == UserRole.MEMBER.value and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own profile."
        )
    return user


# ================================================================
# ✅ Update Another User (Admin only)
# ================================================================
@router.put("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Admin: update a user within your organization."""
    user = session.exec(
        select(User)
        .where(User.id == user_id, User.organization_id == current_user.organization_id)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Scoped email uniqueness
    if user_update.email and user_update.email != user.email:
        existing_user = session.exec(
            select(User).where(
                User.email == user_update.email,
                User.organization_id == current_user.organization_id
            )
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered in this organization."
            )
        user.email = user_update.email

    if user_update.full_name is not None:
        user.full_name = user_update.full_name
    if user_update.role is not None:
        user.role = user_update.role
    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    # Handle profile fields
    if user_update.department is not None:
        user.department = user_update.department
    if user_update.job_title is not None:
        user.job_title = user_update.job_title
    if user_update.phone_number is not None:
        user.phone_number = user_update.phone_number
    if user_update.time_zone is not None:
        user.time_zone = user_update.time_zone
    if user_update.bio is not None:
        user.bio = user_update.bio
    if user_update.skills is not None:
        user.skills = user_update.skills
    if user_update.profile_picture is not None:
        user.profile_picture = user_update.profile_picture

    try:
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    except IntegrityError as e:
        session.rollback()
        error_msg = str(e.orig)
        if "uq_org_email" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered in this organization."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A database constraint was violated."
            )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while updating the user."
        )



# ================================================================
# ✅ Get All Members of Organization
# ================================================================
@router.get("/organization/members", response_model=List[UserRead])
def get_organization_members(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Return all active users in the same organization."""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to any organization."
        )

    members = session.exec(
        select(User)
        .where(
            User.organization_id == current_user.organization_id,
            User.is_active == True
        )
    ).all()
    return members







# ================================================================
# ✅ DELETE USER (Super Admin Only - Permanent Deletion)
# ================================================================

@router.delete("/{user_id}/permanent", status_code=status.HTTP_200_OK)
def delete_user_permanent(
    user_id: int,
    current_user: User = Depends(get_current_user),  # Changed from get_current_admin
    session: Session = Depends(get_session)
):
    """Super Admin only: Permanently delete a user from the organization and database."""
    
    # Only Super Admin can perform permanent deletion
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin can permanently delete users."
        )

    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account."
        )

    # Find user in the same organization
    user = session.exec(
        select(User).where(
            User.id == user_id, 
            User.organization_id == current_user.organization_id
        )
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User not found in your organization."
        )

    try:
        # Permanent deletion from database
        session.delete(user)
        session.commit()
        
        return {
            "success": True, 
            "message": f"User {user.email} has been permanently removed from the organization."
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error while deleting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while deleting the user."
        )