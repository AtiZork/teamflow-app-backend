from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, desc
from datetime import datetime

from core.database import get_session
from core.security import get_current_user
from models.models import User
from .models import Notification, NotificationRecipient, NotificationRead

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=List[NotificationRead])
def get_my_notifications(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get current user's notifications.
    Filtered by organization and user.
    Sorted by latest first.
    """
    # Query: Join Notification and Recipient
    # Select Notification fields + Recipient.is_read
    
    query = (
        select(Notification, NotificationRecipient.is_read, NotificationRecipient.read_at)
        .join(NotificationRecipient, Notification.id == NotificationRecipient.notification_id)
        .where(
            NotificationRecipient.user_id == current_user.id,
            Notification.organization_id == current_user.organization_id
        )
        .order_by(desc(Notification.created_at))
        .offset(offset)
        .limit(limit)
    )
    
    results = session.exec(query).all()
    
    notifications = []
    for noti, is_read, read_at in results:
        # Map to response schema
        notifications.append(NotificationRead(
            id=noti.id,
            type=noti.type,
            title=noti.title,
            message=noti.message,
            entity_type=noti.entity_type,
            entity_id=noti.entity_id,
            created_at=noti.created_at,
            is_read=is_read,
            read_at=read_at
        ))
        
    return notifications

@router.patch("/{notification_id}/read", status_code=204)
def mark_notification_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark a specific notification as read.
    """
    recipient_link = session.exec(
        select(NotificationRecipient).where(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.user_id == current_user.id
        )
    ).first()
    
    if recipient_link and not recipient_link.is_read:
        recipient_link.is_read = True
        recipient_link.read_at = datetime.utcnow()
        session.add(recipient_link)
        session.commit()
