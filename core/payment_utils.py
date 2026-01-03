# core/payment_utils.py
from fastapi import HTTPException, Depends
from sqlmodel import Session, select

from core.database import get_session
from core.security import get_current_user
from models.models import User

def get_payment_eligible_user(current_user: User = Depends(get_current_user)):
    """
    Dependency to get current user only if they are payment eligible
    (publicly signed-up super admin)
    """
    # Check if user is publicly signed-up super admin
    # Based on your auth.py, public signup creates users with role=UserRole.ADMIN.value
    # and is_invited=False
    
    is_payment_eligible = (
        current_user.role in ["admin", "super_admin"] and 
        not getattr(current_user, "is_invited", True)
    )
    
    if not is_payment_eligible:
        raise HTTPException(
            status_code=403,
            detail="Only organization creators can access payment features"
        )
    
    return current_user

def check_payment_visibility(user: User) -> bool:
    """
    Check if payment options should be visible for a user
    """
    # Payment is visible only for publicly signed-up admins/super_admins
    # (organization creators)
    return (
        user.role in ["admin", "super_admin"] and 
        not getattr(user, "is_invited", True)
    )