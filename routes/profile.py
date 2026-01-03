# routes/profile.py
from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    HTTPException,
    status,
)
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime
from pathlib import Path
from fastapi import Form
import os
import logging

from core.database import get_session
from core.security import get_current_user
from models.models import User
from schemas.profile_schema import ProfileRead, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["Profile"])


# ==================================================================
#  ✅  Configuration
# ================================================================== 
UPLOAD_DIR = Path("./uploads/profile_pictures/")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_MB = 5


def get_public_profile_picture_url(file_path: Optional[str]) -> Optional[str]:
    """Convert filesystem path to public URL for profile pictures."""
    if not file_path:
        return None

    if file_path.startswith(("http://", "https://")):
        return file_path

    # ✅ FIX: Match the static file serving path exactly
    # Your logs show files are served from /static/profile_pictures/
    filename = os.path.basename(file_path)
    return f"/static/profile_pictures/{filename}"


def serialize_user(user: User) -> dict:
    """Safely convert SQLModel user instance to JSON-compatible dict."""
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "department": user.department,
        "job_title": user.job_title,
        "phone_number": user.phone_number,
        "time_zone": user.time_zone,
        "bio": user.bio,
        "skills": user.skills,
        "profile_picture": get_public_profile_picture_url(user.profile_picture),
        "organization_id": user.organization_id,
        "created_at": user.created_at,
        "date_joined": user.date_joined,
        "is_public_admin": user.is_public_admin,  # Include new field
        "is_invited": user.is_invited,  # Include is_invited
    }


# ==================================================================
#  ✅  Get Current User Profile
# ================================================================== 

@router.get("/me", response_model=ProfileRead)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Return the current user's profile details."""
    return serialize_user(current_user)


# ==================================================================
#  ✅ Update Current User Profile (With Picture Upload)
# ================================================================== 
@router.put("/me", response_model=ProfileRead)
async def update_my_profile(
    full_name: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    job_title: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    time_zone: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    skills: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        update_data = {
            "full_name": full_name,
            "department": department,
            "job_title": job_title,
            "phone_number": phone_number,
            "time_zone": time_zone,
            "bio": bio,
            "skills": skills,
        }

        # Remove None fields
        update_data = {k: v for k, v in update_data.items() if v is not None}

        # Handle skills
        if "skills" in update_data and isinstance(update_data["skills"], str):
            update_data["skills"] = update_data["skills"]

        # Update model
        for field, value in update_data.items():
            setattr(current_user, field, value)

        # --- Handle profile picture ---
        if file:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only .jpg, .jpeg, and .png files are allowed.",
                )

            contents = await file.read()
            if len(contents) > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File size exceeds {MAX_FILE_SIZE_MB} MB limit.",
                )

            # Delete old
            if current_user.profile_picture and os.path.exists(current_user.profile_picture):
                try:
                    os.remove(current_user.profile_picture)
                except Exception:
                    logging.warning(f"Failed to delete old picture for user {current_user.id}")

            safe_filename = f"user_{current_user.id}_{int(datetime.utcnow().timestamp())}{ext}"
            save_path = UPLOAD_DIR / safe_filename
            with open(save_path, "wb") as f:
                f.write(contents)

            current_user.profile_picture = save_path.as_posix()

        # Commit
        session.add(current_user)
        session.commit()
        session.refresh(current_user)

        logging.info(f"✅ Profile updated successfully for user {current_user.id}")
        return serialize_user(current_user)

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logging.error(f"❌ Profile update failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating your profile.",
        )

# ==================================================================
#  ✅ Get All Organization Members' Profiles
# ================================================================== 
@router.get("/organization/members", response_model=List[ProfileRead])
async def get_org_profiles(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all user profiles in the same organization."""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to any organization.",
        )

    members = session.exec(
        select(User).where(User.organization_id == current_user.organization_id)
    ).all()

    return [serialize_user(member) for member in members]