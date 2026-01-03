# core/security.py
from datetime import datetime, UTC, timedelta
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from core.database import get_session
from core.config import settings
from models.models import User, UserRole
import secrets


# ========================================
# 🔑 JWT / APP CONFIG
# ========================================
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM or "HS256"
# ACCESS_TOKEN_EXPIRE_MINUTES = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24)
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
REFRESH_TOKEN_EXPIRE_DAYS = 7
INVITATION_EXPIRE_HOURS = 48  # 2 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ========================================
# 🔐 Password Hashing (Argon2)
# ========================================
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash password using Argon2."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password using Argon2."""
    return pwd_context.verify(plain_password, hashed_password)


# ========================================
# 🔑 Token Helpers
# ========================================
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode JWT and return payload."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ========================================
# 📧 Invitation Tokens
# ========================================
def generate_invitation_token() -> str:
    """Generate secure random token (fallback for simple invite links)."""
    return secrets.token_urlsafe(32)


# ========================================
# 👤 Authentication & Role Checks
# ========================================
def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User:
    """Extract user from token and load full record from DB."""
    payload = decode_token(token)
    user_id = payload.get("user_id")
    email = payload.get("sub")
    organization_id = payload.get("organization_id")

    if not (user_id or email):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = None
    if user_id:
        user = session.exec(select(User).where(User.id == user_id)).first()
    if not user and email:
        user = session.exec(select(User).where(User.email == email)).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    # Verify organization match if included in token
    # ✅ Allow flexibility for members (invited users might have delayed org sync)
    if organization_id and getattr(user, "organization_id", None):
        if str(user.organization_id) != str(organization_id):
            raise HTTPException(status_code=403, detail="User not part of this organization")
    # If org_id missing (legacy or member invite), just proceed with user org
    elif not getattr(user, "organization_id", None) and organization_id:
        user.organization_id = organization_id

    print(f"DEBUG AUTH: user_id={user.id}, org_in_token={organization_id}, user_org={user.organization_id}, role={user.role}")

    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require Admin or Super Admin."""
    if current_user.role not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


def get_current_member(current_user: User = Depends(get_current_user)) -> User:
    """Allow Member, Admin, or Super Admin."""
    if current_user.role not in [
        UserRole.MEMBER.value,
        UserRole.ADMIN.value,
        UserRole.SUPER_ADMIN.value,
    ]:
        raise HTTPException(status_code=403, detail="Member privileges required")
    return current_user


def get_current_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only Super Admin."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="Super admin privileges required")
    return current_user


# ========================================
# 🔄 Token Pair Utility
# ========================================
def create_tokens_for_user(user: User) -> tuple[str, str]:
    """Return (access, refresh) token pair."""
    data = {
        "sub": user.email,
        "user_id": user.id,
        "organization_id": getattr(user, "organization_id", None),
        "role": getattr(user, "role", None),
    }
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)
    return access_token, refresh_token


def get_current_admin_or_org_user(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # This gets any authenticated user
):
    """
    Get current user and verify they belong to an organization
    (Admins can view all, regular users can only view their own data)
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    return current_user