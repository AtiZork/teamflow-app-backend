from fastapi import APIRouter, HTTPException, Depends, status, Query
from sqlmodel import Session, select
from datetime import datetime
import re
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models.models import User, UserRole, Organization
from schemas.user_schema import UserCreate, UserLogin, UserRead
from core.database import get_session
from core.security import (
    hash_password, verify_password, create_access_token,
    get_current_user
)

router = APIRouter(tags=["Authentication"])


# ==========================================================
# ✅ Helper: Generate clean organization slug
# ==========================================================
def generate_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:50]


# ==========================================================
# ✅ Public Signup — creates organization + super admin user
# ==========================================================
@router.post("/signup")
def public_signup(user_data: UserCreate, session: Session = Depends(get_session)):
    """Creates a new organization and its super admin"""
    try:
        print(f"📝 Signup attempt for {user_data.email}")

        org_name = f"{user_data.full_name}'s Organization"
        org_slug = generate_slug(org_name)

        # ✅ Create Organization
        organization = Organization(
            name=org_name,
            slug=org_slug,
            created_at=datetime.utcnow(),
        )
        session.add(organization)
        session.commit()
        session.refresh(organization)

        # ✅ Create Super Admin User
        new_user = User(
            full_name=user_data.full_name,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            role=UserRole.SUPER_ADMIN.value,
            is_public_admin=True,  # ✅ New field
            organization_id=organization.id,
            is_active=True,
            is_invited=False,
            created_at=datetime.utcnow(),
            date_joined=datetime.utcnow(),
        )

        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        # ✅ Link organization with its super admin
        organization.super_admin_id = new_user.id
        session.add(organization)
        session.commit()

        # ✅ JWT generation
        access_token = create_access_token(
            data={
                "sub": new_user.email,
                "role": new_user.role,
                "user_id": new_user.id,
                "organization_id": new_user.organization_id,
            }
        )

        print(f"DEBUG: JWT payload created for {new_user.email}")

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": new_user.id,
                "full_name": new_user.full_name,
                "email": new_user.email,
                "role": new_user.role,
                "organization_id": new_user.organization_id,
                "is_active": new_user.is_active,
                "created_at": new_user.created_at.isoformat(),
                "is_public_admin": new_user.is_public_admin,  # ✅ Include new field
            },
        }

    except IntegrityError as e:
        session.rollback()
        msg = str(e.orig)
        if "email" in msg:
            raise HTTPException(
                status_code=400,
                detail="An account with this email already exists. Please log in instead."
            )
        raise HTTPException(
            status_code=400,
            detail="We couldn't complete your signup. Please try again later."
        )

    except SQLAlchemyError as e:
        session.rollback()
        print("❌ Database error during signup:", e)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while creating your account. Please try again later."
        )

    except Exception as e:
        session.rollback()
        print("❌ Unexpected signup error:", e)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )


# ==========================================================
# ✅ Login — multi-tenant aware (organization slug optional)
# ==========================================================
@router.post("/login")
def login(
    credentials: UserLogin,
    organization_slug: str = Query(None, description="Organization slug (optional)"),
    session: Session = Depends(get_session),
):
    """Authenticate user within their organization"""
    try:
        # 🔹 Determine organization
        if organization_slug:
            org = session.exec(select(Organization).where(Organization.slug == organization_slug)).first()
            if not org:
                raise HTTPException(status_code=404, detail="Organization not found.")
            org_id = org.id
        else:
            db_user = session.exec(select(User).where(User.email == credentials.email)).first()
            if not db_user:
                raise HTTPException(status_code=404, detail="No account found with this email.")
            org_id = db_user.organization_id

        # 🔹 Fetch user by email + org
        db_user = session.exec(
            select(User)
            .where(User.email == credentials.email, User.organization_id == org_id)
        ).first()

        if not db_user:
            raise HTTPException(status_code=404, detail="Account not found for this organization.")

        if not verify_password(credentials.password, db_user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")

        if not db_user.is_active:
            raise HTTPException(status_code=403, detail="Your account is inactive. Contact your admin.")

        # 🔹 JWT creation
        token = create_access_token(
            data={
                "sub": db_user.email,
                "role": db_user.role,
                "user_id": db_user.id,
                "organization_id": db_user.organization_id,
            }
        )

        print(f"DEBUG: Login successful for {db_user.email}")

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": db_user.id,
                "full_name": db_user.full_name,
                "email": db_user.email,
                "role": db_user.role,
                "organization_id": db_user.organization_id,
                "is_active": db_user.is_active,
                "is_public_admin": db_user.is_public_admin,  # ✅ Include new field
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        print("❌ Login database error:", e)
        raise HTTPException(
            status_code=500,
            detail="We're having trouble logging you in. Please try again later."
        )
    except Exception as e:
        print("❌ Unexpected login error:", e)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while logging in. Please try again."
        )


# ==========================================================
# ✅ Get Current Authenticated User
# ==========================================================
@router.get("/me", response_model=UserRead)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's information"""
    return current_user