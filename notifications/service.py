import logging
from typing import List, Optional
from sqlmodel import Session, select, or_
from sqlalchemy.exc import SQLAlchemyError

from .models import Notification, NotificationRecipient, NotificationType
from models.models import User, UserRole

# Configure logger
logger = logging.getLogger("teamflow.notifications")

def create_notification(
    session: Session,
    organization_id: int,
    sender_id: Optional[int],
    recipient_ids: List[int],
    type: str,
    title: str,
    message: str,
    entity_type: str,
    entity_id: int
) -> None:
    """
    Safely create a notification and its recipients.
    
    CRITICAL DESIGN RULES:
    1. Must use try/except to catch ALL errors.
    2. Must log errors but NEVER raise exceptions.
    3. Must ensure that if this fails, the core transaction is NOT marked for rollback.
       We achieve this using a nested transaction (SAVEPOINT).
    """
    if not recipient_ids:
        return

    try:
        # Begin a nested transaction (SAVEPOINT)
        # If anything happens inside, it rolls back only to this point.
        with session.begin_nested():
            # 1. Create Notification Record
            notification = Notification(
                organization_id=organization_id,
                sender_id=sender_id,
                type=type,
                title=title,
                message=message,
                entity_type=entity_type,
                entity_id=entity_id
            )
            session.add(notification)
            session.flush()  # ID is generated here
            
            # 2. Add Recipients
            # Deduplicate recipient_ids just in case
            unique_recipients = set(recipient_ids)
            
            for form_user_id in unique_recipients:
                recipient = NotificationRecipient(
                    notification_id=notification.id,
                    user_id=form_user_id
                )
                session.add(recipient)
            
            # Use flush to verify constraint integrity immediately within the safe block
            session.flush()

    except Exception as e:
        # Log the error safely
        logger.error(f"❌ Failed to create notification [Type: {type}, Org: {organization_id}]: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Do NOT raise exception.
        pass


def notify_organization_admins(
    session: Session,
    organization_id: int,
    sender_id: Optional[int],
    type: str,
    title: str,
    message: str,
    entity_type: str,
    entity_id: int
) -> None:
    """
    Helper to notify all admins and super admins of an organization.
    """
    try:
        # Find all admins/super_admins for this org
        # Use .value for string comparison to ensure DB match
        statement = select(User.id).where(
            User.organization_id == organization_id,
            or_(
                User.role == UserRole.ADMIN.value,
                User.role == UserRole.SUPER_ADMIN.value
            ),
            User.is_active == True
        )
        
        admin_ids = session.exec(statement).all()
        logger.info(f"🔔 Notifying {len(admin_ids)} admins in Org {organization_id} (Type: {type})")
        logger.info(f"   Admin IDs found: {admin_ids}")
        logger.debug(f"Found {len(admin_ids)} admins to notify in organization {organization_id}")
        
        # We include all admins (even if sender) for consistent testing/visibility
        recipient_ids = admin_ids
        
        if recipient_ids:
            create_notification(
                session=session,
                organization_id=organization_id,
                sender_id=sender_id,
                recipient_ids=recipient_ids,
                type=type,
                title=title,
                message=message,
                entity_type=entity_type,
                entity_id=entity_id
            )
            
    except Exception as e:
        logger.error(f"Failed to notify admins [Org: {organization_id}]: {str(e)}")
        pass

