# file: scripts/init_leave_types.py
"""
Script to initialize default leave types for organizations.
Run this once or include in your startup script.
"""
from sqlmodel import Session, select
from datetime import datetime, UTC
from core.database import engine
from models.leave_models import LeaveType, LeaveTypeCode
from models.models import Organization

def init_default_leave_types():
    """Initialize default leave types for all organizations."""
    with Session(engine) as session:
        # Get all organizations
        organizations = session.exec(select(Organization)).all()
        
        for org in organizations:
            # Check if organization already has leave types
            existing_types = session.exec(
                select(LeaveType).where(LeaveType.organization_id == org.id)
            ).all()
            
            if existing_types:
                print(f"Organization {org.name} already has leave types. Skipping.")
                continue
            
            # Define default leave types
            default_types = [
                {
                    "name": "Annual Leave",
                    "code": LeaveTypeCode.ANNUAL.value,
                    "yearly_limit": 20,
                    "description": "Paid annual vacation leave"
                },
                {
                    "name": "Sick Leave",
                    "code": LeaveTypeCode.SICK.value,
                    "yearly_limit": 10,
                    "description": "Paid sick leave for medical reasons"
                },
                {
                    "name": "Personal Leave",
                    "code": LeaveTypeCode.PERSONAL.value,
                    "yearly_limit": 5,
                    "description": "Paid personal/emergency leave"
                },
                {
                    "name": "Unpaid Leave",
                    "code": LeaveTypeCode.UNPAID.value,
                    "yearly_limit": 0,  # Unlimited
                    "description": "Unpaid leave for extended time off"
                }
            ]
            
            # Create leave types
            for type_data in default_types:
                leave_type = LeaveType(
                    **type_data,
                    organization_id=org.id,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )
                session.add(leave_type)
            
            session.commit()
            print(f"Created default leave types for organization: {org.name}")
        
        print("✅ Default leave types initialized for all organizations.")

if __name__ == "__main__":
    init_default_leave_types()