"""
Leave Management API for Multi-Tenant System
Handles leave applications, approvals, and tracking with tenant isolation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional, Dict, Any
from datetime import datetime, date as date_type, timedelta, timezone

# Use timezone.utc since UTC alias might need direct import or Python 3.11+
UTC = timezone.utc
from sqlmodel import Session, select, func, and_, or_

from core.database import get_session
from core.security import get_current_user, get_current_admin
from models.models import User, Organization
from models.leave_models import LeaveRequest, LeaveBalance, LeaveType
from notifications.service import notify_organization_admins
from notifications.models import NotificationType
from schemas.leave_schemas import (
    LeaveTypeSchema,
    LeaveBalanceSchema,
    LeaveRequestCreate,
    LeaveRequestUpdate,
    LeaveRequestSchema,
    LeaveStatsSchema,
    EmployeeLeaveBalanceSummary,
    LeaveBalanceUpdateRequest,
    BulkLeaveBalanceUpdate,
    LeaveOverviewResponse,
    UnpaidLeaveValidation,
    LeaveOverlapCheck,
    LeaveApplicationValidation
)

router = APIRouter(prefix="/leave", tags=["leave-management"])


# ============================================================
# ✅ HELPER FUNCTIONS
# ============================================================

def _get_org_id_from_user(current_user: User) -> int:
    """Extract organization ID from user"""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not associated with an organization"
        )
    return current_user.organization_id


def _calculate_duration_days(start_date: date_type, end_date: date_type) -> int:
    """Calculate duration in working days (excluding weekends)"""
    days = 0
    current_date = start_date
    while current_date <= end_date:
        # Skip weekends (5=Saturday, 6=Sunday)
        if current_date.weekday() < 5:
            days += 1
        current_date += timedelta(days=1)
    return days


def _check_leave_overlap(
    session: Session,
    user_id: int,
    org_id: int,
    start_date: date_type,
    end_date: date_type,
    exclude_request_id: Optional[int] = None
) -> bool:
    """Check if user has overlapping leave requests"""
    query = select(LeaveRequest).where(
        and_(
            LeaveRequest.user_id == user_id,
            LeaveRequest.organization_id == org_id,
            LeaveRequest.status.in_(["pending", "approved"]),
            or_(
                and_(
                    LeaveRequest.start_date <= end_date,
                    LeaveRequest.end_date >= start_date
                )
            )
        )
    )
    
    if exclude_request_id:
        query = query.where(LeaveRequest.id != exclude_request_id)
    
    overlapping = session.exec(query).first()
    return overlapping is not None


def _get_leave_balance_record(
    session: Session,
    user_id: int,
    leave_type_id: int,
    org_id: int,
    year: int
) -> Optional[LeaveBalance]:
    """Get leave balance record for specific user, type, and year"""
    balance = session.exec(
        select(LeaveBalance).where(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.leave_type_id == leave_type_id,
                LeaveBalance.organization_id == org_id,
                LeaveBalance.fiscal_year == year
            )
        )
    ).first()
    
    return balance


def _validate_leave_application(
    session: Session,
    user_id: int,
    org_id: int,
    leave_type_id: int,
    start_date: date_type,
    end_date: date_type,
    duration_days: int
) -> LeaveApplicationValidation:
    """Validate leave application including balance and overlap checks"""
    
    # Get leave type
    leave_type = session.get(LeaveType, leave_type_id)
    if not leave_type:
        return LeaveApplicationValidation(
            is_valid=False,
            has_sufficient_balance=False,
            has_overlap=False,
            message="Leave type not found",
            errors=["Invalid leave type"]
        )
    
    # Check for overlapping leaves
    has_overlap = _check_leave_overlap(session, user_id, org_id, start_date, end_date)
    
    # For unpaid leave, special validation
    if not leave_type.is_paid:
        unpaid_validation = _validate_unpaid_leave_request(
            session, user_id, org_id, leave_type_id, duration_days
        )
        
        return LeaveApplicationValidation(
            is_valid=unpaid_validation.can_apply_unpaid and not has_overlap,
            has_sufficient_balance=unpaid_validation.can_apply_unpaid,
            has_overlap=has_overlap,
            unpaid_validation=unpaid_validation,
            message=unpaid_validation.message,
            errors=["Overlapping leave request"] if has_overlap else []
        )
    
    # For paid leave, check balance
    year = start_date.year
    balance = _get_leave_balance_record(session, user_id, leave_type_id, org_id, year)
    
    if not balance:
        # Create default balance if doesn't exist
        balance = LeaveBalance(
            user_id=user_id,
            organization_id=org_id,
            leave_type_id=leave_type_id,
            total_days=leave_type.max_days,
            used_days=0,
            remaining_days=leave_type.max_days,
            fiscal_year=year,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC)
        )
        session.add(balance)
        session.commit()
        session.refresh(balance)
    
    has_sufficient_balance = balance.remaining_days >= duration_days
    
    # Construct errors list manually to ensure no None values are included
    errors = []
    if not has_sufficient_balance:
        errors.append(f"Insufficient balance: {balance.remaining_days} remaining, need {duration_days}")
    
    if has_overlap:
        errors.append("Overlapping leave request found")

    return LeaveApplicationValidation(
        is_valid=has_sufficient_balance and not has_overlap,
        has_sufficient_balance=has_sufficient_balance,
        has_overlap=has_overlap,
        message=f"{'Sufficient balance' if has_sufficient_balance else 'Insufficient balance'}. "
                f"{'No overlapping leaves' if not has_overlap else 'Overlapping leave found'}",
        errors=errors,
        warnings=[],
        available_balance=balance.remaining_days if balance else 0,
        requested_days=duration_days
    )


def _validate_unpaid_leave_request(
    session: Session,
    user_id: int,
    org_id: int,
    leave_type_id: int,
    duration_days: int
) -> UnpaidLeaveValidation:
    """Validate unpaid leave request according to business rules"""
    
    # Get unpaid leave type
    unpaid_type = session.get(LeaveType, leave_type_id)
    if not unpaid_type or unpaid_type.is_paid:
        return UnpaidLeaveValidation(
            has_sufficient_paid_balance=False,
            total_paid_remaining=0,
            can_apply_unpaid=False,
            message="Invalid unpaid leave type"
        )
    
    # Get all paid leave types for the organization
    paid_types = session.exec(
        select(LeaveType).where(
            and_(
                LeaveType.organization_id == org_id,
                LeaveType.is_paid == True
            )
        )
    ).all()
    
    # Calculate total paid leave remaining
    current_year = datetime.now(UTC).year
    total_paid_remaining = 0
    
    for paid_type in paid_types:
        balance = _get_leave_balance_record(
            session, user_id, paid_type.id, org_id, current_year
        )
        if balance:
            total_paid_remaining += balance.remaining_days
        else:
            # If no balance record exists, assume full allocation
            total_paid_remaining += paid_type.max_days
    
    # Rule: Can apply for unpaid only if all paid leaves are exhausted
    can_apply_unpaid = total_paid_remaining == 0
    
    # Get unpaid balance
    unpaid_balance = _get_leave_balance_record(
        session, user_id, leave_type_id, org_id, current_year
    )
    
    message = ""
    if not can_apply_unpaid:
        message = f"Cannot apply for unpaid leave. You still have {total_paid_remaining} paid leave days remaining."
    elif unpaid_balance and unpaid_balance.remaining_days < duration_days:
        message = f"Insufficient unpaid leave balance. You have {unpaid_balance.remaining_days} days remaining, but need {duration_days}."
        can_apply_unpaid = False
    elif not unpaid_balance or unpaid_balance.total_days == 0:
        message = "No unpaid leave allocated. Admin must allocate unpaid days before approval."
        # Still allow application, but admin needs to allocate
        can_apply_unpaid = True
    else:
        message = f"Unpaid leave application valid. Balance: {unpaid_balance.remaining_days}/{unpaid_balance.total_days} days"
    
    return UnpaidLeaveValidation(
        has_sufficient_paid_balance=total_paid_remaining == 0,
        total_paid_remaining=total_paid_remaining,
        unpaid_balance=unpaid_balance,
        can_apply_unpaid=can_apply_unpaid,
        message=message
    )


def _update_leave_balance_on_approval(
    session: Session,
    leave_request: LeaveRequest,
    is_approval: bool = True
):
    """Update leave balance when leave is approved or cancelled"""
    
    # Get leave type
    leave_type = session.get(LeaveType, leave_request.leave_type_id)
    if not leave_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave type not found"
        )
    
    # For unpaid leave, check if balance exists
    if not leave_type.is_paid:
        balance = _get_leave_balance_record(
            session,
            leave_request.user_id,
            leave_request.leave_type_id,
            leave_request.organization_id,
            leave_request.year
        )
        
        if not balance or balance.total_days == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve unpaid leave without allocated balance. "
                       "Admin must allocate unpaid days first."
            )
    
    # Get or create balance record
    balance = _get_leave_balance_record(
        session,
        leave_request.user_id,
        leave_request.leave_type_id,
        leave_request.organization_id,
        leave_request.year
    )
    
    if not balance:
        # Create balance record if it doesn't exist
        balance = LeaveBalance(
            user_id=leave_request.user_id,
            organization_id=leave_request.organization_id,
            leave_type_id=leave_request.leave_type_id,
            total_days=leave_type.max_days,
            used_days=0,
            remaining_days=leave_type.max_days,
            fiscal_year=leave_request.year,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC)
        )
        session.add(balance)
        session.commit()
        session.refresh(balance)
    
    # Update balance based on approval/cancellation
    if is_approval:  # Approving leave
        if balance.remaining_days < leave_request.duration_days:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient balance. Available: {balance.remaining_days}, "
                       f"Requested: {leave_request.duration_days}"
            )
        
        balance.used_days += leave_request.duration_days
        balance.remaining_days = max(0, balance.total_days - balance.used_days)
    else:  # Cancelling approved leave (restore balance)
        balance.used_days = max(0, balance.used_days - leave_request.duration_days)
        balance.remaining_days = balance.total_days - balance.used_days
    
    balance.updated_at = datetime.now(UTC)
    session.add(balance)
    session.commit()


def _ensure_admin_permissions(current_user: User, org_id: int) -> None:
    """Ensure user has admin permissions for organization"""
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    if current_user.organization_id != org_id and current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot manage leave balances outside your organization"
        )


# ============================================================
# 👤 USER ENDPOINTS
# ============================================================

@router.get("/types", response_model=List[LeaveTypeSchema])
async def get_leave_types(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get all available leave types for current organization"""
    org_id = _get_org_id_from_user(current_user)
    
    leave_types = session.exec(
        select(LeaveType).where(
            LeaveType.organization_id == org_id
        ).order_by(LeaveType.name)
    ).all()
    
    return leave_types


@router.get("/balance", response_model=List[LeaveBalanceSchema])
async def get_my_leave_balance(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get current user's leave balance for current fiscal year"""
    org_id = _get_org_id_from_user(current_user)
    current_year = datetime.now(UTC).year
    
    # Get all leave types for organization
    leave_types = session.exec(
        select(LeaveType).where(
            LeaveType.organization_id == org_id
        )
    ).all()
    
    balances = []
    
    for leave_type in leave_types:
        # Get existing balance
        balance = session.exec(
            select(LeaveBalance).where(
                and_(
                    LeaveBalance.user_id == current_user.id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.organization_id == org_id,
                    LeaveBalance.fiscal_year == current_year
                )
            )
        ).first()
        
        if not balance:
            # Create default balance for display
            total_days = leave_type.max_days
            # For unpaid leave, start at 0 instead of 365
            if not leave_type.is_paid:
                total_days = 0
            
            balance = LeaveBalance(
                id=0,  # Virtual ID for response
                user_id=current_user.id,
                organization_id=org_id,
                leave_type_id=leave_type.id,
                total_days=total_days,
                used_days=0,
                remaining_days=total_days,
                fiscal_year=current_year,
                leave_type=leave_type
            )
        
        balances.append(balance)
    
    return balances


@router.get("/my-requests", response_model=List[LeaveRequestSchema])
async def get_my_leave_requests(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    status: Optional[str] = Query(None),
    year: Optional[int] = Query(None)
):
    """Get current user's leave requests"""
    org_id = _get_org_id_from_user(current_user)
    
    query = select(LeaveRequest).where(
        and_(
            LeaveRequest.user_id == current_user.id,
            LeaveRequest.organization_id == org_id
        )
    )
    
    if status:
        query = query.where(LeaveRequest.status == status)
    
    if year:
        query = query.where(LeaveRequest.year == year)
    
    query = query.order_by(LeaveRequest.created_at.desc())
    
    requests = session.exec(query).all()
    
    response = []
    for req in requests:
        # Get related user information
        handover_person = None
        if req.handover_person_id:
            handover_person = session.get(User, req.handover_person_id)
        
        approved_by = None
        if req.approved_by:
            approved_by = session.get(User, req.approved_by)
        
        response.append(
            LeaveRequestSchema(
                id=req.id,
                user_id=req.user_id,
                organization_id=req.organization_id,
                employee_name=current_user.full_name,
                employee_role=current_user.role,
                leave_type_id=req.leave_type_id,
                leave_type_name=req.leave_type.name if req.leave_type else "Unknown",
                start_date=req.start_date,
                end_date=req.end_date,
                duration_days=req.duration_days,
                reason=req.reason,
                emergency_contact=req.emergency_contact,
                handover_person_id=req.handover_person_id,
                handover_person_name=handover_person.full_name if handover_person else None,
                handover_notes=req.handover_notes,
                status=req.status,
                submitted_at=req.submitted_at,
                admin_comments=req.admin_comments,
                approved_by=req.approved_by,
                approved_by_name=approved_by.full_name if approved_by else None,
                approved_at=req.approved_at,
                created_at=req.created_at,
                updated_at=req.updated_at
            )
        )
    
    return response


@router.post("/apply", response_model=LeaveRequestSchema, status_code=status.HTTP_201_CREATED)
async def apply_for_leave(
    leave_data: LeaveRequestCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Apply for leave with validation"""
    org_id = _get_org_id_from_user(current_user)
    
    # Validate leave type exists in organization
    leave_type = session.exec(
        select(LeaveType).where(
            and_(
                LeaveType.id == leave_data.leave_type_id,
                LeaveType.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave type not found in your organization"
        )
    
    # Calculate duration
    duration_days = _calculate_duration_days(
        leave_data.start_date,
        leave_data.end_date
    )
    
    if duration_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date range or duration (must be > 0 working days)"
        )
    
    # Validate leave application
    validation = _validate_leave_application(
        session=session,
        user_id=current_user.id,
        org_id=org_id,
        leave_type_id=leave_data.leave_type_id,
        start_date=leave_data.start_date,
        end_date=leave_data.end_date,
        duration_days=duration_days
    )
    
    if not validation.is_valid:
        error_msg = validation.message
        if validation.errors:
            error_msg += f" Errors: {', '.join([e for e in validation.errors if e])}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Create leave request
    leave_request = LeaveRequest(
        user_id=current_user.id,
        organization_id=org_id,
        leave_type_id=leave_data.leave_type_id,
        start_date=leave_data.start_date,
        end_date=leave_data.end_date,
        duration_days=duration_days,
        reason=leave_data.reason,
        emergency_contact=leave_data.emergency_contact,
        handover_person_id=leave_data.handover_person_id,
        handover_notes=leave_data.handover_notes,
        status="pending",
        submitted_at=datetime.now(UTC),
        year=leave_data.start_date.year,
        month=leave_data.start_date.month,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    
    session.add(leave_request)
    session.flush() # Ensure ID is populated for notification
    
    # ✅ NOTIFICATION HOOK
    notify_organization_admins(
        session=session,
        organization_id=org_id,
        sender_id=current_user.id,
        type=NotificationType.LEAVE_APPLIED,
        title="New Leave Application",
        message=f"{current_user.full_name} applied for {duration_days} day(s) leave",
        entity_type="leave",
        entity_id=leave_request.id
    )

    session.commit()
    session.refresh(leave_request)
    
    # Get related user information for response
    handover_person = None
    if leave_request.handover_person_id:
        handover_person = session.get(User, leave_request.handover_person_id)
    
    return LeaveRequestSchema(
        id=leave_request.id,
        user_id=leave_request.user_id,
        organization_id=leave_request.organization_id,
        employee_name=current_user.full_name,
        employee_role=current_user.role,
        leave_type_id=leave_request.leave_type_id,
        leave_type_name=leave_type.name,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        duration_days=leave_request.duration_days,
        reason=leave_request.reason,
        emergency_contact=leave_request.emergency_contact,
        handover_person_id=leave_request.handover_person_id,
        handover_person_name=handover_person.full_name if handover_person else None,
        handover_notes=leave_request.handover_notes,
        status=leave_request.status,
        submitted_at=leave_request.submitted_at,
        admin_comments=leave_request.admin_comments,
        approved_by=leave_request.approved_by,
        approved_by_name=None,
        approved_at=leave_request.approved_at,
        created_at=leave_request.created_at,
        updated_at=leave_request.updated_at
    )


@router.patch("/requests/{request_id}/cancel")
async def cancel_leave_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Cancel a leave request (user or admin)"""
    org_id = _get_org_id_from_user(current_user)
    
    # Get leave request
    leave_request = session.exec(
        select(LeaveRequest).where(
            and_(
                LeaveRequest.id == request_id,
                LeaveRequest.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found"
        )
    
    # Check permissions
    is_admin = current_user.role in ["admin", "super_admin"]
    if not is_admin and leave_request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own leave requests"
        )
    
    # Check if cancellation is allowed
    if leave_request.status not in ["pending", "approved"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a {leave_request.status} leave request"
        )
    
    # If approved, restore leave balance
    if leave_request.status == "approved":
        try:
            _update_leave_balance_on_approval(
                session, leave_request, is_approval=False
            )
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restore leave balance: {str(e)}"
            )
    
    # Update status
    leave_request.status = "cancelled"
    leave_request.updated_at = datetime.now(UTC)
    
    session.add(leave_request)
    session.commit()
    
    return {"message": "Leave request cancelled successfully"}


# ============================================================
# 👨‍💼 ADMIN ENDPOINTS
# ============================================================

@router.get("/admin/requests", response_model=List[LeaveRequestSchema])
async def get_all_leave_requests(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    status: Optional[str] = Query(None),
    employee_id: Optional[int] = Query(None),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    leave_type_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get all leave requests in admin's organization"""
    org_id = _get_org_id_from_user(current_user)
    
    # Build query with organization filter
    query = select(LeaveRequest).where(
        LeaveRequest.organization_id == org_id
    )
    
    # Apply filters
    if status:
        query = query.where(LeaveRequest.status == status)
    
    if employee_id:
        # Verify employee is in same organization
        employee = session.get(User, employee_id)
        if not employee or employee.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found in your organization"
            )
        query = query.where(LeaveRequest.user_id == employee_id)
    
    if start_date:
        query = query.where(LeaveRequest.start_date >= start_date)
    
    if end_date:
        query = query.where(LeaveRequest.end_date <= end_date)
    
    if leave_type_id:
        query = query.where(LeaveRequest.leave_type_id == leave_type_id)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_count = session.exec(count_query).one()
    
    # Apply pagination
    query = query.order_by(LeaveRequest.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)
    
    requests = session.exec(query).all()
    
    # Build response with user information
    response = []
    for req in requests:
        employee = session.get(User, req.user_id)
        handover_person = session.get(User, req.handover_person_id) if req.handover_person_id else None
        approved_by = session.get(User, req.approved_by) if req.approved_by else None
        
        response.append(
            LeaveRequestSchema(
                id=req.id,
                user_id=req.user_id,
                organization_id=req.organization_id,
                employee_name=employee.full_name if employee else "Unknown",
                employee_role=employee.role if employee else "Unknown",
                leave_type_id=req.leave_type_id,
                leave_type_name=req.leave_type.name if req.leave_type else "Unknown",
                start_date=req.start_date,
                end_date=req.end_date,
                duration_days=req.duration_days,
                reason=req.reason,
                emergency_contact=req.emergency_contact,
                handover_person_id=req.handover_person_id,
                handover_person_name=handover_person.full_name if handover_person else None,
                handover_notes=req.handover_notes,
                status=req.status,
                submitted_at=req.submitted_at,
                admin_comments=req.admin_comments,
                approved_by=req.approved_by,
                approved_by_name=approved_by.full_name if approved_by else None,
                approved_at=req.approved_at,
                created_at=req.created_at,
                updated_at=req.updated_at
            )
        )
    
    return response


@router.patch("/admin/requests/{request_id}/approve")
async def approve_leave_request(
    request_id: int,
    update_data: LeaveRequestUpdate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Approve a leave request and deduct from balance"""
    org_id = _get_org_id_from_user(current_user)
    
    # Get leave request
    leave_request = session.exec(
        select(LeaveRequest).where(
            and_(
                LeaveRequest.id == request_id,
                LeaveRequest.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found in your organization"
        )
    
    if leave_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Leave request is already {leave_request.status}"
        )
    
    # Update leave balance before changing status
    try:
        _update_leave_balance_on_approval(session, leave_request, is_approval=True)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update leave balance: {str(e)}"
        )
    
    # Update leave request
    leave_request.status = "approved"
    leave_request.admin_comments = update_data.admin_comments
    leave_request.approved_by = current_user.id
    leave_request.approved_at = datetime.now(UTC)
    leave_request.updated_at = datetime.now(UTC)
    
    session.add(leave_request)
    session.commit()
    
    return {"message": "Leave request approved successfully"}


@router.patch("/admin/requests/{request_id}/reject")
async def reject_leave_request(
    request_id: int,
    update_data: LeaveRequestUpdate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Reject a leave request (no balance changes)"""
    org_id = _get_org_id_from_user(current_user)
    
    # Get leave request
    leave_request = session.exec(
        select(LeaveRequest).where(
            and_(
                LeaveRequest.id == request_id,
                LeaveRequest.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found in your organization"
        )
    
    if leave_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Leave request is already {leave_request.status}"
        )
    
    # Update leave request
    leave_request.status = "rejected"
    leave_request.admin_comments = update_data.admin_comments
    leave_request.approved_by = current_user.id
    leave_request.approved_at = datetime.now(UTC)
    leave_request.updated_at = datetime.now(UTC)
    
    session.add(leave_request)
    session.commit()
    
    return {"message": "Leave request rejected successfully"}


@router.get("/admin/employee/{employee_id}/balance", response_model=List[LeaveBalanceSchema])
async def get_employee_leave_balance(
    employee_id: int,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Get employee leave balance (admin only)"""
    org_id = _get_org_id_from_user(current_user)
    current_year = datetime.now(UTC).year
    
    # Verify employee exists in same organization
    employee = session.exec(
        select(User).where(
            and_(
                User.id == employee_id,
                User.organization_id == org_id
            )
        )
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found in your organization"
        )
    
    # Get all leave types for organization
    leave_types = session.exec(
        select(LeaveType).where(
            LeaveType.organization_id == org_id
        )
    ).all()
    
    balances = []
    
    for leave_type in leave_types:
        # Get existing balance
        balance = session.exec(
            select(LeaveBalance).where(
                and_(
                    LeaveBalance.user_id == employee_id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.organization_id == org_id,
                    LeaveBalance.fiscal_year == current_year
                )
            )
        ).first()
        
        if not balance:
            # Create default balance for display
            total_days = leave_type.max_days
            # For unpaid leave, start at 0 instead of 365
            if not leave_type.is_paid:
                total_days = 0
            
            balance = LeaveBalance(
                id=0,  # Virtual ID for response
                user_id=employee_id,
                organization_id=org_id,
                leave_type_id=leave_type.id,
                total_days=total_days,
                used_days=0,
                remaining_days=total_days,
                fiscal_year=current_year,
                leave_type=leave_type
            )
        
        balances.append(balance)
    
    return balances


@router.post("/admin/employee/{employee_id}/balance/manage")
async def manage_employee_leave_balance(
    employee_id: int,
    update_data: LeaveBalanceUpdateRequest,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Manage employee leave balance (admin only) - Primary use: allocate unpaid leave"""
    org_id = _get_org_id_from_user(current_user)
    current_year = update_data.effective_date.year if update_data.effective_date else datetime.now(UTC).year
    
    # Verify employee exists in same organization
    employee = session.exec(
        select(User).where(
            and_(
                User.id == employee_id,
                User.organization_id == org_id
            )
        )
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found in your organization"
        )
    
    # Get leave type
    leave_type = session.exec(
        select(LeaveType).where(
            and_(
                LeaveType.id == update_data.leave_type_id,
                LeaveType.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave type not found in your organization"
        )
    
    # Get current balance
    balance = session.exec(
        select(LeaveBalance).where(
            and_(
                LeaveBalance.user_id == employee_id,
                LeaveBalance.leave_type_id == update_data.leave_type_id,
                LeaveBalance.organization_id == org_id,
                LeaveBalance.fiscal_year == current_year
            )
        )
    ).first()
    
    if not balance:
        # Create new balance record
        if update_data.action == 'set':
            total_days = update_data.days
        elif update_data.action == 'add':
            total_days = update_data.days
        else:  # subtract from 0 doesn't make sense
            total_days = 0
        
        balance = LeaveBalance(
            user_id=employee_id,
            organization_id=org_id,
            leave_type_id=update_data.leave_type_id,
            total_days=total_days,
            used_days=0,
            remaining_days=total_days,
            fiscal_year=current_year,
            notes=update_data.notes,
            last_updated_by=current_user.id,
            last_updated_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC)
        )
    else:
        # Update existing balance
        old_total = balance.total_days
        old_used = balance.used_days
        old_remaining = balance.remaining_days
        
        if update_data.action == 'add':
            balance.total_days += update_data.days
            balance.remaining_days += update_data.days
        elif update_data.action == 'subtract':
            # Ensure we don't go negative
            new_total = max(0, balance.total_days - update_data.days)
            # Adjust used days if needed
            if balance.used_days > new_total:
                balance.used_days = new_total
            balance.total_days = new_total
            balance.remaining_days = new_total - balance.used_days
        elif update_data.action == 'set':
            balance.total_days = update_data.days
            # Ensure used days doesn't exceed new total
            if balance.used_days > update_data.days:
                balance.used_days = update_data.days
            balance.remaining_days = update_data.days - balance.used_days
        
        balance.notes = update_data.notes
        balance.last_updated_by = current_user.id
        balance.last_updated_at = datetime.now(UTC)
        balance.updated_at = datetime.now(UTC)
    
    session.add(balance)
    session.commit()
    session.refresh(balance)
    
    # Get leave type info for response
    balance.leave_type = leave_type
    
    return {
        "message": f"Leave balance updated successfully for {employee.full_name}",
        "balance": LeaveBalanceSchema.from_orm(balance)
    }


@router.get("/admin/employees/balance-summary", response_model=List[EmployeeLeaveBalanceSummary])
async def get_employees_balance_summary(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    department: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get leave balance summary for all employees"""
    org_id = _get_org_id_from_user(current_user)
    current_year = datetime.now(UTC).year
    
    # Build employee query
    query = select(User).where(
        and_(
            User.organization_id == org_id,
            User.is_active == True
        )
    )
    
    if department:
        query = query.where(User.department == department)
    
    # Pagination
    employees = session.exec(
        query.order_by(User.full_name)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    
    response = []
    
    for employee in employees:
        # Get all leave balances for employee
        balances_query = select(LeaveBalance).where(
            and_(
                LeaveBalance.user_id == employee.id,
                LeaveBalance.organization_id == org_id,
                LeaveBalance.fiscal_year == current_year
            )
        )
        balances = session.exec(balances_query).all()
        
        # Calculate totals
        total_remaining = sum(b.remaining_days for b in balances)
        total_used = sum(b.used_days for b in balances)
        
        # Get last leave request
        last_request = session.exec(
            select(LeaveRequest)
            .where(LeaveRequest.user_id == employee.id)
            .order_by(LeaveRequest.created_at.desc())
            .limit(1)
        ).first()
        
        # Convert balances to schema
        balance_schemas = []
        for balance in balances:
            if not balance.leave_type:
                balance.leave_type = session.get(LeaveType, balance.leave_type_id)
            
            balance_schemas.append(
                LeaveBalanceSchema(
                    id=balance.id,
                    user_id=balance.user_id,
                    leave_type_id=balance.leave_type_id,
                    total_days=balance.total_days,
                    used_days=balance.used_days,
                    remaining_days=balance.remaining_days,
                    fiscal_year=balance.fiscal_year,
                    leave_type=LeaveTypeSchema.from_orm(balance.leave_type),
                    organization_id=balance.organization_id
                )
            )
        
        response.append(
            EmployeeLeaveBalanceSummary(
                employee_id=employee.id,
                employee_name=employee.full_name,
                email=employee.email,
                role=employee.role,
                department=employee.department,
                organization_id=employee.organization_id,
                leave_balances=balance_schemas,
                total_remaining=total_remaining,
                total_used=total_used,
                last_leave_request=last_request.created_at if last_request else None
            )
        )
    
    return response


@router.post("/admin/balance/bulk-update")
async def bulk_update_leave_balances(
    bulk_data: BulkLeaveBalanceUpdate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Bulk update leave balances for multiple employees"""
    org_id = _get_org_id_from_user(current_user)
    current_year = datetime.now(UTC).year
    
    # Verify leave type exists in organization
    leave_type = session.exec(
        select(LeaveType).where(
            and_(
                LeaveType.id == bulk_data.leave_type_id,
                LeaveType.organization_id == org_id
            )
        )
    ).first()
    
    if not leave_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave type not found in your organization"
        )
    
    results = []
    errors = []
    
    for employee_id in bulk_data.employee_ids:
        try:
            # Verify employee exists in organization
            employee = session.exec(
                select(User).where(
                    and_(
                        User.id == employee_id,
                        User.organization_id == org_id
                    )
                )
            ).first()
            
            if not employee:
                errors.append({
                    "employee_id": employee_id,
                    "error": "Employee not found in organization"
                })
                continue
            
            # Get current balance
            balance = session.exec(
                select(LeaveBalance).where(
                    and_(
                        LeaveBalance.user_id == employee_id,
                        LeaveBalance.leave_type_id == bulk_data.leave_type_id,
                        LeaveBalance.organization_id == org_id,
                        LeaveBalance.fiscal_year == current_year
                    )
                )
            ).first()
            
            old_values = {
                "total_days": balance.total_days if balance else 0,
                "used_days": balance.used_days if balance else 0,
                "remaining_days": balance.remaining_days if balance else 0
            }
            
            if not balance:
                # Create new balance
                if bulk_data.action == 'set':
                    total_days = bulk_data.days
                elif bulk_data.action == 'add':
                    total_days = bulk_data.days
                else:
                    total_days = 0
                
                balance = LeaveBalance(
                    user_id=employee_id,
                    organization_id=org_id,
                    leave_type_id=bulk_data.leave_type_id,
                    total_days=total_days,
                    used_days=0,
                    remaining_days=total_days,
                    fiscal_year=current_year,
                    notes=bulk_data.notes,
                    last_updated_by=current_user.id,
                    last_updated_at=datetime.now(UTC),
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC)
                )
            else:
                # Update existing balance
                if bulk_data.action == 'add':
                    balance.total_days += bulk_data.days
                    balance.remaining_days += bulk_data.days
                elif bulk_data.action == 'subtract':
                    new_total = max(0, balance.total_days - bulk_data.days)
                    if balance.used_days > new_total:
                        balance.used_days = new_total
                    balance.total_days = new_total
                    balance.remaining_days = new_total - balance.used_days
                elif bulk_data.action == 'set':
                    balance.total_days = bulk_data.days
                    if balance.used_days > bulk_data.days:
                        balance.used_days = bulk_data.days
                    balance.remaining_days = bulk_data.days - balance.used_days
                
                balance.notes = bulk_data.notes
                balance.last_updated_by = current_user.id
                balance.last_updated_at = datetime.now(UTC)
                balance.updated_at = datetime.now(UTC)
            
            session.add(balance)
            session.commit()
            session.refresh(balance)
            
            results.append({
                "employee_id": employee_id,
                "employee_name": employee.full_name,
                "success": True,
                "old_balance": old_values,
                "new_balance": {
                    "total_days": balance.total_days,
                    "used_days": balance.used_days,
                    "remaining_days": balance.remaining_days
                }
            })
            
        except Exception as e:
            errors.append({
                "employee_id": employee_id,
                "error": str(e)
            })
            session.rollback()
            continue
    
    return {
        "message": f"Bulk update completed: {len(results)} successful, {len(errors)} failed",
        "results": results,
        "errors": errors
    }


@router.get("/admin/stats", response_model=LeaveStatsSchema)
async def get_leave_stats(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None)
):
    """Get leave statistics for organization"""
    org_id = _get_org_id_from_user(current_user)
    
    # Build query
    query = select(LeaveRequest).where(
        LeaveRequest.organization_id == org_id
    )
    
    if start_date:
        query = query.where(LeaveRequest.start_date >= start_date)
    
    if end_date:
        query = query.where(LeaveRequest.end_date <= end_date)
    
    requests = session.exec(query).all()
    
    # Calculate statistics
    total_requests = len(requests)
    pending = sum(1 for r in requests if r.status == "pending")
    approved = sum(1 for r in requests if r.status == "approved")
    rejected = sum(1 for r in requests if r.status == "rejected")
    
    # This month
    current_month = datetime.now(UTC).month
    this_month = sum(1 for r in requests if r.start_date.month == current_month)
    
    # Average duration of approved leaves
    approved_requests = [r for r in requests if r.status == "approved"]
    avg_duration = sum(r.duration_days for r in approved_requests) / len(approved_requests) if approved_requests else 0
    
    # Leave type distribution
    leave_type_dist = {}
    for r in requests:
        if r.leave_type:
            leave_type_name = r.leave_type.name
            leave_type_dist[leave_type_name] = leave_type_dist.get(leave_type_name, 0) + 1
    
    return LeaveStatsSchema(
        total_requests=total_requests,
        pending=pending,
        approved=approved,
        rejected=rejected,
        this_month=this_month,
        average_duration=round(avg_duration, 1),
        leave_type_distribution=leave_type_dist,
        organization_id=org_id
    )