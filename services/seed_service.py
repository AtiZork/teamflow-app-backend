"""
Production-Ready Leave Type Initialization Service

WHY THIS EXISTS:
--------------
In production (Render, Railway, Fly.io), databases start fresh on deploy.
Without automatic initialization:
- Leave types table is empty
- Frontend shows empty dropdowns
- Users cannot create leave requests
- Manual database seeding is error-prone and not scalable

This service automatically seeds default leave types on application startup
for any organization that doesn't have them yet.

DESIGN PRINCIPLES:
-----------------
1. IDEMPOTENT: Safe to run multiple times - never creates duplicates
2. ORGANIZATION-AWARE: Respects multi-tenant isolation
3. TRANSACTIONAL: Atomic operations with rollback on failure
4. SAFE ON REDEPLOY: Checks existing data before inserting
5. NO MANUAL SCRIPTS: Runs automatically via FastAPI lifespan
6. PRODUCTION-READY: Comprehensive logging and error handling

GUARANTEES:
----------
✅ Never creates duplicate leave types
✅ Only seeds organizations without existing types
✅ Rolls back on any error to prevent partial state
✅ Works reliably across all cloud providers
✅ Logs all operations for debugging
"""

from sqlmodel import Session, select
from models.models import Organization
from models.leave_models import LeaveType
from core.database import engine
import logging
from typing import List, Dict

# Configure logging for production debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# DEFAULT LEAVE TYPES CONFIGURATION
# ============================================================
# These are the standard leave types created for every organization
# on first initialization. Customize these to match your organization's
# leave policies.

DEFAULT_LEAVE_TYPES: List[Dict] = [
    {
        "name": "Annual Leave",
        "max_days": 20,
        "description": "Paid annual leave for vacation and leisure",
        "is_paid": True,
        "color": "#3B82F6",  # Blue
        "icon": "FiCalendar"
    },
    {
        "name": "Sick Leave",
        "max_days": 10,
        "description": "Paid sick leave for medical reasons",
        "is_paid": True,
        "color": "#EF4444",  # Red
        "icon": "FiHeart"
    },
    {
        "name": "Personal Leave",
        "max_days": 5,
        "description": "Paid personal leave for personal matters",
        "is_paid": True,
        "color": "#8B5CF6",  # Purple
        "icon": "FiUser"
    },
    {
        "name": "Unpaid Leave",
        "max_days": 0,  # 0 means unlimited/not tracked
        "description": "Unpaid leave for any purpose",
        "is_paid": False,
        "color": "#6B7280",  # Gray
        "icon": "FiClock"
    }
]


def seed_default_leave_types() -> None:
    """
    Initialize default leave types for all organizations.
    
    This function is called automatically during FastAPI application startup
    via the lifespan event in main.py.
    
    BEHAVIOR:
    ---------
    1. Queries all organizations in the database
    2. For each organization:
       a. Checks if leave types already exist
       b. If no leave types exist, seeds the default types
       c. Commits the transaction atomically
    3. Logs all operations for production debugging
    
    IDEMPOTENCY:
    -----------
    This function is safe to call multiple times:
    - Checks existing leave types before insertion
    - Never creates duplicates
    - Skips organizations that already have leave types
    
    ERROR HANDLING:
    --------------
    - Uses database transactions with automatic rollback
    - Logs all errors with organization context
    - Continues processing other organizations if one fails
    - Never leaves the database in a partial state
    
    PRODUCTION LOGGING:
    ------------------
    - INFO: Successful operations (seeding completed)
    - DEBUG: Skip operations (already has types)
    - ERROR: Failed operations with full traceback
    
    Returns:
        None
        
    Raises:
        Does not raise - all errors are caught and logged
    """
    
    try:
        logger.info("🚀 Starting leave types initialization...")
        
        # Open a database session with automatic cleanup
        with Session(engine) as session:
            # Fetch all organizations
            organizations = session.exec(select(Organization)).all()
            
            if not organizations:
                logger.warning("⚠️  No organizations found in database. Skipping leave type seeding.")
                return
            
            logger.info(f"📊 Found {len(organizations)} organization(s) in database.")
            
            seeded_count = 0
            skipped_count = 0
            
            # Process each organization independently
            for org in organizations:
                try:
                    # Check if this organization already has leave types
                    # This is the IDEMPOTENCY CHECK - prevents duplicates
                    existing_types = session.exec(
                        select(LeaveType).where(LeaveType.organization_id == org.id)
                    ).all()
                    
                    if existing_types:
                        # Organization already has leave types - skip
                        logger.debug(
                            f"⏭️  Organization '{org.name}' (ID: {org.id}) already has "
                            f"{len(existing_types)} leave type(s). Skipping."
                        )
                        skipped_count += 1
                        continue
                    
                    # Seed default leave types for this organization
                    logger.info(
                        f"🌱 Seeding {len(DEFAULT_LEAVE_TYPES)} default leave types for "
                        f"Organization: '{org.name}' (ID: {org.id})"
                    )
                    
                    # Create each leave type
                    for leave_type_data in DEFAULT_LEAVE_TYPES:
                        leave_type = LeaveType(
                            **leave_type_data,
                            organization_id=org.id  # Tenant isolation
                        )
                        session.add(leave_type)
                    
                    # Commit atomically - all types created or none
                    session.commit()
                    seeded_count += 1
                    
                    logger.info(
                        f"✅ Successfully seeded leave types for '{org.name}' (ID: {org.id})"
                    )
                    
                except Exception as org_error:
                    # Log error for this specific organization
                    logger.error(
                        f"❌ Failed to seed leave types for Organization '{org.name}' (ID: {org.id}): {org_error}",
                        exc_info=True
                    )
                    # Rollback this organization's transaction
                    session.rollback()
                    # Continue with next organization
                    continue
            
            # Summary logging
            logger.info(
                f"✅ Leave type initialization complete. "
                f"Seeded: {seeded_count} | Skipped: {skipped_count} | Total: {len(organizations)}"
            )
                    
    except Exception as e:
        # Catch-all for unexpected errors
        logger.error(
            f"❌ Critical error during leave type initialization: {e}",
            exc_info=True
        )


# ============================================================
# ADDITIONAL UTILITY FUNCTIONS (Optional)
# ============================================================

def verify_leave_types_for_organization(organization_id: int) -> bool:
    """
    Verify that an organization has leave types configured.
    
    Useful for:
    - Health checks
    - Debugging production issues
    - Validating data migration
    
    Args:
        organization_id: The organization ID to check
        
    Returns:
        True if organization has leave types, False otherwise
    """
    try:
        with Session(engine) as session:
            existing_types = session.exec(
                select(LeaveType).where(LeaveType.organization_id == organization_id)
            ).all()
            return len(existing_types) > 0
    except Exception as e:
        logger.error(f"Error verifying leave types for org {organization_id}: {e}")
        return False


def get_leave_type_count_for_organization(organization_id: int) -> int:
    """
    Get the count of leave types for an organization.
    
    Args:
        organization_id: The organization ID to check
        
    Returns:
        Number of leave types configured for the organization
    """
    try:
        with Session(engine) as session:
            existing_types = session.exec(
                select(LeaveType).where(LeaveType.organization_id == organization_id)
            ).all()
            return len(existing_types)
    except Exception as e:
        logger.error(f"Error counting leave types for org {organization_id}: {e}")
        return 0
