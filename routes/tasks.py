# routes/tasks.py
from fastapi import APIRouter, HTTPException, Depends, status, Query
from sqlmodel import Session, select, desc
from typing import List, Optional, Dict
from datetime import datetime, timedelta, date
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload

from core.database import get_session
from models.models import (
    Task, Project, User, TaskMemberLink, UserRole, 
    TaskComment, TaskWorkLog, Organization
)
from core.security import get_current_user, get_current_admin

from schemas.task_schema import (
    TaskCreate,
    TaskUpdate,
    TaskRead as TaskOut,
    CommentCreate,
    CommentRead as CommentOut,
    WorkLogCreate,
    WorkLogRead as WorkLogOut
)
from notifications.service import create_notification, notify_organization_admins
from notifications.models import NotificationType


router = APIRouter(tags=["Tasks"])


# ================================================================
#  ✅ Helper function to check if user is assigned to task
# ================================================================
def _is_user_assigned_to_task(session: Session, user_id: int, task_id: int) -> bool:
    assignment = session.exec(
        select(TaskMemberLink).where(
            TaskMemberLink.task_id == task_id,
            TaskMemberLink.user_id == user_id
        )
    ).first()
    return assignment is not None


# ================================================================
#  ✅ Helper function to check task access
# ================================================================
def _check_task_access(session: Session, task: Task, current_user: User) -> bool:
    """Check if user has access to the task"""
    if task.organization_id != current_user.organization_id:
        return False
    
    if current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
        return True
    
    # For members, check if they're assigned to the task
    if current_user.role == UserRole.MEMBER.value:
        return _is_user_assigned_to_task(session, current_user.id, task.id)
    
    return False


# ================================================================
#  ✅ Create New Task with Organization
# ================================================================
@router.post("/", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Create a new task.
    Only admins can create tasks.
    Includes project_name in response.
    """
    # --- Validate project ownership ---
    project = session.exec(
        select(Project).where(
            Project.id == payload.project_id,
            Project.organization_id == current_user.organization_id
        )
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or not in your organization"
        )

    # --- Create task ---
    # ✅ Set start_date to current date if not provided
    start_date = payload.start_date or datetime.utcnow()
    
    task = Task(
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        start_date=start_date,  # ✅ NEW FIELD
        due_date=payload.due_date,
        project_id=payload.project_id,
        organization_id=current_user.organization_id,
        allow_member_edit=payload.allow_member_edit,
    )

    try:
        session.add(task)
        session.commit()
        session.refresh(task)

        # --- Handle member assignment ---
        member_ids = payload.member_ids or []
        if member_ids:
            valid_member_ids = []
            for member_id in member_ids:
                member = session.exec(
                    select(User).where(
                        User.id == member_id,
                        User.organization_id == current_user.organization_id
                    )
                ).first()
                if member:
                    task_member_link = TaskMemberLink(
                        task_id=task.id,
                        user_id=member_id,
                        organization_id=current_user.organization_id,
                    )
                    session.add(task_member_link)
                    valid_member_ids.append(member_id)
            session.commit()
        else:
            valid_member_ids = []

        # --- Build and return response ---
        project_name = project.title if project else None

        response_data = {
            **task.dict(),
            "member_ids": valid_member_ids,
            "project_name": project_name,
        }

        # ✅ NOTIFICATION: Task Assigned
        # We do this after return? No, can't code after return.
        # So we move return to end.
        
        # We need to construct response before notification 
        # because create_notification is safe (won't crash).
        
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A database constraint was violated while creating the task."
        )
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while creating the task."
        )

    # ✅ NOTIFICATION INTEGRATION (SAFE)
    if valid_member_ids:
        create_notification(
            session=session,
            organization_id=current_user.organization_id,
            sender_id=current_user.id,
            recipient_ids=valid_member_ids,
            type=NotificationType.TASK_ASSIGNED,
            title="New Task Assigned",
            message=f"You have been assigned to task: {task.title}",
            entity_type="task",
            entity_id=task.id
        )

    return TaskOut.from_orm(task)

# ================================================================
#  ✅ Get All Tasks (Organization-scoped)
# ================================================================

@router.get("/", response_model=List[TaskOut])
def get_tasks(
    project_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Retrieve all tasks for the current user's organization.
    - Admins/Super Admins see all tasks in the organization.
    - Members see only the tasks they are assigned to.
    """
    organization_id = current_user.organization_id

    # --- Base query ---
    if current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
        query = select(Task).where(Task.organization_id == organization_id)
    else:
        query = (
            select(Task)
            .join(TaskMemberLink)
            .where(
                Task.organization_id == organization_id,
                TaskMemberLink.user_id == current_user.id,
            )
        )

    # --- Filters ---
    if project_id:
        query = query.where(Task.project_id == project_id)
    if status_filter:
        query = query.where(Task.status == status_filter)

    query = query.order_by(Task.created_at.desc())
    tasks = session.exec(query).all()

    if not tasks:
        return []

    # --- Prefetch related projects to avoid N+1 ---
    project_ids = {t.project_id for t in tasks}
    projects = session.exec(select(Project).where(Project.id.in_(project_ids))).all()
    project_map = {p.id: p.title for p in projects}

    # --- Build response ---
    task_out_list = []
    for task in tasks:
        project_name = project_map.get(task.project_id)
        # Ensure member_ids are included (if Task has a relationship or link table)
        member_links = session.exec(
            select(TaskMemberLink.user_id).where(TaskMemberLink.task_id == task.id)
        ).all()
        member_ids = [m[0] if isinstance(m, tuple) else m for m in member_links]

        task_out = TaskOut.model_validate(
            {
                **task.dict(),
                "member_ids": member_ids,
                "project_name": project_name,
            }
        )
        task_out_list.append(task_out)

    return task_out_list


# ================================================================
#  ✅ Get Single Task
# ================================================================
@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get a single task by ID.
    Admins can view any task in their organization.
    Members can only view tasks assigned to them.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    return TaskOut.model_validate(task)


# ================================================================
#   ✅ Update Task
# ================================================================
# In tasks.py - Update the update_task function
@router.put("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Update a task.
    Members can only update their own tasks' status.
    Admins can update any task in their organization.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this task"
        )
    
    # For members, restrict what they can update
    is_admin_user = current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]
    if not is_admin_user:
        # Check if task allows member editing
        if not task.allow_member_edit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This task does not allow member editing"
            )
        
        # Allow only status update for members
        allowed_fields = {'status'}
        provided_fields = set(payload.dict(exclude_unset=True).keys())
        if not provided_fields.issubset(allowed_fields):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Members can only update task status"
            )
    
    # Update task fields
    update_data = payload.dict(exclude_unset=True, exclude={'member_ids'})
    for key, value in update_data.items():
        setattr(task, key, value)
    
    # ✅ FIXED: Handle member updates (only for admins)
    if is_admin_user and 'member_ids' in payload.dict(exclude_unset=True):
        member_ids = payload.member_ids or []
        
        # Remove existing member links using proper SQLModel approach
        existing_links = session.exec(
            select(TaskMemberLink).where(TaskMemberLink.task_id == task_id)
        ).all()
        for link in existing_links:
            session.delete(link)
        
        # Add new member links
        for member_id in member_ids:
            # Verify member belongs to the same organization
            member = session.exec(
                select(User).where(
                    User.id == member_id,
                    User.organization_id == current_user.organization_id
                )
            ).first()
            
            if member:
                task_member_link = TaskMemberLink(
                    task_id=task_id,
                    user_id=member_id,
                    organization_id=current_user.organization_id
                )
                session.add(task_member_link)
        
        # ✅ NOTIFICATION: Task Assignment Update
        if member_ids:
            create_notification(
                session=session,
                organization_id=current_user.organization_id,
                sender_id=current_user.id,
                recipient_ids=member_ids,
                type=NotificationType.TASK_ASSIGNED,
                title="Task Assigned",
                message=f"You have been assigned to task: {task.title}",
                entity_type="task",
                entity_id=task.id
            )
    
    try:
        session.add(task)
        session.commit()
        session.refresh(task)
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A database constraint was violated while updating the task."
        )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while updating the task."
        )
    
    # ✅ NOTIFICATION: Status Changed
    # We need to check if status changed. 
    # But we already updated the task object.
    # To do this safely, we should have checked specific changes before commit.
    # BUT, since we have strict instructions not to refactor logic too much, 
    # we can check if 'status' was in payload and assume it changed.
    # Better: check if status in update_data.
    
    if 'status' in update_data:
        # 1. Notify Admins if a member changed the status
        if not is_admin_user:
            notify_organization_admins(
                session=session,
                organization_id=current_user.organization_id,
                sender_id=current_user.id,
                type=NotificationType.TASK_STATUS_CHANGED,
                title="Task Status Updated",
                message=f"{current_user.full_name} updated task '{task.title}' status to {task.status}",
                entity_type="task",
                entity_id=task.id
            )
        
        # 2. Notify assignees (if admin changed it or if there are other members)
        assignee_links = session.exec(
            select(TaskMemberLink).where(TaskMemberLink.task_id == task_id)
        ).all()
        recipient_ids = [link.user_id for link in assignee_links if link.user_id != current_user.id]

        if recipient_ids:
            create_notification(
                session=session,
                organization_id=current_user.organization_id,
                sender_id=current_user.id,
                recipient_ids=recipient_ids,
                type=NotificationType.TASK_STATUS_CHANGED,
                title="Task Status Updated",
                message=f"Task '{task.title}' status changed to {task.status}",
                entity_type="task",
                entity_id=task.id
            )
        
        # ✅ Commit the notifications specifically
        try:
            session.commit()
        except:
            session.rollback()
            # We don't raise error here because core task update already succeeded
            pass

    return TaskOut.model_validate(task)

# ================================================================
#   ✅ Delete Task
# ================================================================
@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Delete a task.
    Only admins can delete tasks.
    This will also remove related TaskComment, TaskWorkLog and TaskMemberLink rows.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check organization access
    if task.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    try:
        # Delete related comments using proper SQLModel approach
        comments = session.exec(
            select(TaskComment).where(TaskComment.task_id == task_id)
        ).all()
        for comment in comments:
            session.delete(comment)

        # Delete related work logs
        work_logs = session.exec(
            select(TaskWorkLog).where(TaskWorkLog.task_id == task_id)
        ).all()
        for work_log in work_logs:
            session.delete(work_log)

        # Delete task-member links
        member_links = session.exec(
            select(TaskMemberLink).where(TaskMemberLink.task_id == task_id)
        ).all()
        for link in member_links:
            session.delete(link)

        # Finally delete the task itself
        session.delete(task)
        session.commit()
        
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A database constraint was violated while deleting the task."
        )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while deleting the task."
        )


# ================================================================
#  ✅ Assign Members to Task
# ================================================================
@router.post("/{task_id}/assign", response_model=TaskOut)
def assign_members_to_task(
    task_id: int,
    member_ids: List[int],
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Assign members to a task.
    Only admins can assign members to tasks.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check organization access
    if task.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    # Remove existing assignments using proper SQLModel approach
    existing_links = session.exec(
        select(TaskMemberLink).where(TaskMemberLink.task_id == task_id)
    ).all()
    for link in existing_links:
        session.delete(link)

    # Add new assignments
    for member_id in member_ids:
        # Verify member belongs to the same organization
        member = session.exec(
            select(User).where(
                User.id == member_id,
                User.organization_id == current_user.organization_id
            )
        ).first()
        
        if member:
            task_member_link = TaskMemberLink(
                task_id=task_id,
                user_id=member_id,
                organization_id=current_user.organization_id
            )
            session.add(task_member_link)

    session.commit()
    session.refresh(task)

    # ✅ NOTIFICATION: Members Assigned
    create_notification(
        session=session,
        organization_id=current_user.organization_id,
        sender_id=current_user.id,
        recipient_ids=member_ids,
        type=NotificationType.TASK_ASSIGNED,
        title="New Task Assigned",
        message=f"You have been assigned to task: {task.title}",
        entity_type="task",
        entity_id=task.id
    )

    return TaskOut.model_validate(task)


# ================================================================
#  ✅ GET TASK COMMENTS
# ================================================================
@router.get("/{task_id}/comments", response_model=List[CommentOut])
def get_task_comments(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get all comments for a task.
    Users can only view comments for tasks they have access to.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    comments = session.exec(
        select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.desc())
    ).all()

    return [CommentOut.model_validate(comment) for comment in comments]


# ================================================================
#  ✅ CREATE TASK COMMENTS
# ================================================================
@router.post("/{task_id}/comments", response_model=CommentOut, status_code=201)
def create_task_comment(
    task_id: int,
    payload: CommentCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Add a comment to a task.
    Users can comment on tasks they have access to.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    comment = TaskComment(
        task_id=task_id,
        user_id=current_user.id,
        message=payload.message,
        organization_id=current_user.organization_id
    )
    
    session.add(comment)
    session.commit()
    session.refresh(comment)

    return CommentOut.model_validate(comment)


# ================================================================
# ✅ GET TASK WORK LOGS
# ================================================================
@router.get("/{task_id}/worklogs", response_model=List[WorkLogOut])
def get_task_work_logs(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get all work logs for a task.
    Users can only view work logs for tasks they have access to.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    work_logs = session.exec(
        select(TaskWorkLog)
        .where(TaskWorkLog.task_id == task_id)
        .order_by(TaskWorkLog.date.desc())
    ).all()

    return [WorkLogOut.model_validate(work_log) for work_log in work_logs]


# ================================================================
# ✅ CREATE TASK WORK LOGS
# ================================================================
@router.post("/{task_id}/worklogs", response_model=WorkLogOut, status_code=201)
def create_task_work_log(
    task_id: int,
    payload: WorkLogCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Add a work log to a task.
    Users can log work on tasks they have access to.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this task"
        )

    work_log = TaskWorkLog(
        task_id=task_id,
        user_id=current_user.id,
        hours=payload.hours,
        description=payload.description,
        date=payload.date or datetime.utcnow(),
        organization_id=current_user.organization_id
    )
    
    session.add(work_log)
    session.commit()
    session.refresh(work_log)

    return WorkLogOut.model_validate(work_log)


# ================================================================
# ✅ DELETE TASK COMMENT
# ================================================================
@router.delete("/comments/{comment_id}", status_code=204)
def delete_task_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Delete a task comment.
    Users can only delete their own comments.
    Admins can delete any comment in their organization.
    """
    comment = session.get(TaskComment, comment_id)
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found"
        )

    # Check organization access
    if comment.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this comment"
        )

    # Check if user owns the comment or is admin
    is_admin = current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]
    if not is_admin and comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own comments"
        )

    session.delete(comment)
    session.commit()


# ================================================================
# ✅ DELETE TASK WORK LOG
# ================================================================
@router.delete("/worklogs/{worklog_id}", status_code=204)
def delete_task_work_log(
    worklog_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Delete a task work log.
    Users can only delete their own work logs.
    Admins can delete any work log in their organization.
    """
    work_log = session.get(TaskWorkLog, worklog_id)
    if not work_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Work log not found"
        )

    # Check organization access
    if work_log.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this work log"
        )

    # Check if user owns the work log or is admin
    is_admin = current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]
    if not is_admin and work_log.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own work logs"
        )

    session.delete(work_log)
    session.commit()


# ================================================================
#  ✅ Update Task Status Only (for drag/drop and member updates)
# ================================================================
@router.patch("/{task_id}/status", response_model=TaskOut)
def update_task_status(
    task_id: int,
    status: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Update only the status of a task.
    Members can use this endpoint to update task status even if allow_member_edit is False.
    """
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access permissions
    if not _check_task_access(session, task, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this task"
        )

    # Update only the status
    task.status = status

    try:
        session.add(task)
        session.commit()
        session.refresh(task)
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while updating the task status."
        )

    # ✅ NOTIFICATION: Status Changed
    # 1. Notify Admins if a member changed the status
    is_admin_user = current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]
    if not is_admin_user:
        notify_organization_admins(
            session=session,
            organization_id=current_user.organization_id,
            sender_id=current_user.id,
            type=NotificationType.TASK_STATUS_CHANGED,
            title="Task Status Updated",
            message=f"{current_user.full_name} updated task '{task.title}' status to {task.status}",
            entity_type="task",
            entity_id=task.id
        )

    # 2. Notify other assignees
    assignee_links = session.exec(
        select(TaskMemberLink).where(TaskMemberLink.task_id == task_id)
    ).all()
    recipient_ids = [link.user_id for link in assignee_links if link.user_id != current_user.id]

    if recipient_ids:
        create_notification(
            session=session,
            organization_id=current_user.organization_id,
            sender_id=current_user.id,
            recipient_ids=recipient_ids,
            type=NotificationType.TASK_STATUS_CHANGED,
            title="Task Status Updated",
            message=f"Task '{task.title}' status changed to {task.status}",
            entity_type="task",
            entity_id=task.id
        )
    
    # ✅ FINAL COMMIT: Save notifications
    try:
        session.commit()
    except:
        session.rollback()
        pass

    return TaskOut.model_validate(task)









# ================================================================
# ✅ Search Tasks with Multiple Filters
# ================================================================

from schemas.task_schema import TaskSearchSchema
from sqlmodel import and_, or_

@router.post("/search", response_model=List[TaskOut])
def search_tasks(
    filters: TaskSearchSchema,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Advanced task search with multiple filters.
    Returns tasks matching any provided filters (tenant-scoped).
    """
    organization_id = current_user.organization_id

    # Base query - organization scoped
    if current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]:
        query = select(Task).where(Task.organization_id == organization_id)
    else:
        # For members, only show tasks they're assigned to
        query = (
            select(Task)
            .join(TaskMemberLink)
            .where(
                Task.organization_id == organization_id,
                TaskMemberLink.user_id == current_user.id,
            )
        )

    # Build dynamic filters
    conditions = []

    # Date range filters
    if filters.from_date:
        conditions.append(Task.created_at >= filters.from_date)
    if filters.to_date:
        # Include the entire day for to_date
        to_date_end = filters.to_date.replace(hour=23, minute=59, second=59)
        conditions.append(Task.created_at <= to_date_end)

    # Text search filters
    if filters.title:
        conditions.append(Task.title.ilike(f"%{filters.title}%"))
    if filters.status:
        conditions.append(Task.status == filters.status)
    if filters.priority:
        conditions.append(Task.priority == filters.priority)

    # Assigned user filter
    if filters.assigned_to:
        # Try to parse as user ID first, then search by name
        try:
            user_id = int(filters.assigned_to)
            # Search by user ID
            user_condition = Task.members.any(User.id == user_id)
            conditions.append(user_condition)
        except ValueError:
            # Search by user name (case-insensitive)
            user_condition = Task.members.any(
                User.full_name.ilike(f"%{filters.assigned_to}%")
            )
            conditions.append(user_condition)

    # Apply all conditions with AND logic
    if conditions:
        query = query.where(and_(*conditions))

    # Order by creation date (newest first)
    query = query.order_by(Task.created_at.desc())

    try:
        tasks = session.exec(query).all()
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while searching tasks."
        )

    if not tasks:
        return []

    # Prefetch related data for response
    project_ids = {t.project_id for t in tasks}
    projects = session.exec(select(Project).where(Project.id.in_(project_ids))).all()
    project_map = {p.id: p.title for p in projects}

    # Get all member IDs across all tasks
    all_member_ids = set()
    for task in tasks:
        member_links = session.exec(
            select(TaskMemberLink.user_id).where(TaskMemberLink.task_id == task.id)
        ).all()
        for member_id in member_links:
            all_member_ids.add(member_id[0] if isinstance(member_id, tuple) else member_id)

    # Fetch all member details in one query
    members = session.exec(select(User).where(User.id.in_(all_member_ids))).all()
    member_map = {member.id: member.full_name for member in members}

    # Build response with member_ids and member_names
    task_out_list = []
    for task in tasks:
        project_name = project_map.get(task.project_id)
        
        # Get assigned member IDs and names
        member_links = session.exec(
            select(TaskMemberLink.user_id).where(TaskMemberLink.task_id == task.id)
        ).all()
        
        member_ids = []
        member_names = []
        for member_link in member_links:
            member_id = member_link[0] if isinstance(member_link, tuple) else member_link
            member_ids.append(member_id)
            member_name = member_map.get(member_id, "Unknown")
            member_names.append(member_name)

        task_out = TaskOut.model_validate(
            {
                **task.dict(),
                "member_ids": member_ids,
                "member_names": member_names,  # Add member names
                "project_name": project_name,
            }
        )
        task_out_list.append(task_out)

    return task_out_list









# Add this to routes/tasks.py after the existing routes

# ================================================================
# ✅ Get User Tasks with Time Logs and Weekly Aggregation
# ================================================================
@router.get("/user/{user_id}/task-logs", response_model=Dict)
def get_user_task_logs_with_weekly_summary(
    user_id: int,
    weeks_back: Optional[int] = Query(12, description="Number of weeks to look back"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get all tasks assigned to a user with time logs and weekly aggregation.
    Returns tasks with details, time logs, and weekly total hours.
    """
    # Verify the target user exists and belongs to the same organization
    target_user = session.exec(
        select(User).where(
            User.id == user_id,
            User.organization_id == current_user.organization_id
        )
    ).first()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in organization"
        )

    # Check permissions - users can only view their own data unless they're admin
    is_admin = current_user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]
    if not is_admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own task logs"
        )

    # Get all tasks assigned to this user
    assigned_tasks_query = (
        select(Task)
        .join(TaskMemberLink, TaskMemberLink.task_id == Task.id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskMemberLink.user_id == user_id,
            Task.organization_id == current_user.organization_id
        )
        .options(joinedload(Task.project))
    )
    assigned_tasks = session.exec(assigned_tasks_query).all()

    # Calculate date range for work logs (last X weeks)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(weeks=weeks_back)
    
    # Get all work logs for this user within the date range
    work_logs_query = (
        select(TaskWorkLog)
        .join(Task, Task.id == TaskWorkLog.task_id)
        .where(
            TaskWorkLog.user_id == user_id,
            TaskWorkLog.organization_id == current_user.organization_id,
            TaskWorkLog.date >= start_date,
            TaskWorkLog.date <= end_date
        )
        .order_by(desc(TaskWorkLog.date))
    )
    work_logs = session.exec(work_logs_query).all()

    # Create task details mapping
    task_details = {}
    for task in assigned_tasks:
        task_details[task.id] = {
            "task_id": task.id,
            "task_title": task.title,
            "task_description": task.description,
            "project_id": task.project_id,
            "project_name": task.project.title if task.project else "Unknown Project",
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date,
            "start_date": getattr(task, 'start_date', None),
            "estimated_hours": getattr(task, 'estimated_hours', 0) or 0,
            "time_logs": [],
            "total_logged_hours": 0.0
        }

    # Group work logs by task and calculate totals
    weekly_aggregation = {}
    
    for work_log in work_logs:
        task_id = work_log.task_id
        
        # Skip if task is not in assigned tasks (shouldn't happen, but safety check)
        if task_id not in task_details:
            continue
            
        # Add time log to task
        log_entry = {
            "log_id": work_log.id,
            "date": work_log.date.date() if isinstance(work_log.date, datetime) else work_log.date,
            "hours": work_log.hours,
            "description": work_log.description,
            "logged_at": work_log.created_at if hasattr(work_log, 'created_at') else None
        }
        task_details[task_id]["time_logs"].append(log_entry)
        task_details[task_id]["total_logged_hours"] += work_log.hours
        
        # Calculate weekly aggregation (Monday to Sunday)
        log_date = work_log.date.date() if isinstance(work_log.date, datetime) else work_log.date
        week_start, week_end = get_week_dates(log_date)
        week_key = week_start.isoformat()
        
        if week_key not in weekly_aggregation:
            weekly_aggregation[week_key] = {
                "week_start": week_start,
                "week_end": week_end,
                "total_hours": 0.0,
                "task_count": 0,
                "log_count": 0
            }
        
        weekly_aggregation[week_key]["total_hours"] += work_log.hours
        weekly_aggregation[week_key]["log_count"] += 1

    # Count tasks per week
    for week_data in weekly_aggregation.values():
        week_tasks = set()
        for task_id, task_data in task_details.items():
            for log in task_data["time_logs"]:
                log_date = log["date"]
                week_start, week_end = get_week_dates(log_date)
                if week_data["week_start"] == week_start:
                    week_tasks.add(task_id)
        week_data["task_count"] = len(week_tasks)

    # Convert task_details to list and sort by total logged hours (descending)
    tasks_list = list(task_details.values())
    tasks_list.sort(key=lambda x: x["total_logged_hours"], reverse=True)
    
    # Sort weekly aggregation by week (descending)
    sorted_weekly = dict(sorted(
        weekly_aggregation.items(), 
        key=lambda x: x[1]["week_start"], 
        reverse=True
    ))

    return {
        "user_id": user_id,
        "user_name": target_user.full_name,
        "user_email": target_user.email,
        "date_range": {
            "start_date": start_date.date().isoformat(),
            "end_date": end_date.date().isoformat(),
            "weeks_back": weeks_back
        },
        "summary": {
            "total_tasks": len(assigned_tasks),
            "total_logged_hours": sum(task["total_logged_hours"] for task in tasks_list),
            "total_work_logs": len(work_logs),
            "weeks_with_data": len(weekly_aggregation)
        },
        "tasks": tasks_list,
        "weekly_aggregation": sorted_weekly
    }


# Helper function for week calculations (add this at the top with other helpers if not exists)
def get_week_dates(target_date: date) -> tuple[date, date]:
    """Get week start (Monday) and end (Sunday) for a given date"""
    weekday = target_date.weekday()  # Monday=0, Sunday=6
    week_start = target_date - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start, week_end