# routes/projects.py
from fastapi import APIRouter, HTTPException, Depends, status
from sqlmodel import Session, select
from typing import List
from datetime import datetime
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import desc
from core.database import get_session
from models.models import Project, User
from schemas.project_schema import ProjectCreate, ProjectRead
from core.security import get_current_user

router = APIRouter(tags=["Projects"])

# ==================================================================
#  ✅ Create New Project with Organization
# ================================================================== 
@router.post("/", response_model=ProjectRead)
def create_project(
    data: ProjectCreate, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # Handle title/name mapping for backward compatibility
    project = Project(
        title=data.title,  # ✅ Map name to title
        description=data.description,
        creator_id=current_user.id or 0,
        organization_id=current_user.organization_id,
        tenant_id=current_user.organization_id,  # ✅ Add tenant_id
        created_at=datetime.utcnow()
    )
    try:
        session.add(project)
        session.commit()
        session.refresh(project)
        
        # Return with name field for frontend compatibility
        response_data = ProjectRead.model_validate(project)
        response_data.title = project.title  # ✅ Map title back to name for response
        return response_data
        
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A project with this name may already exist in your organization."
        )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while creating the project."
        )

# ==================================================================
#  ✅ Get All Projects (filtered by organization)
# ================================================================== 
@router.get("/", response_model=List[ProjectRead])
def get_projects(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    # Only get projects from the user's organization
    projects = session.exec(
        select(Project)
        .where(Project.organization_id == current_user.organization_id)
        .order_by(desc(Project.created_at))
    ).all()
    
    # Map title to name for frontend compatibility
    response_projects = []
    for project in projects:
        project_data = ProjectRead.model_validate(project)
        project_data.title = project.title
        response_projects.append(project_data)
    
    return response_projects

# ==================================================================
#  ✅ Get Single Project (with organization check)
# ================================================================== 
@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if project belongs to user's organization
    if project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")
    
    # Map title to name for frontend compatibility
    project_data = ProjectRead.model_validate(project)
    project_data.title = project.title
    return project_data

# ==================================================================
#  ✅ Update Project (with organization check)
# ================================================================== 
@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, 
    data: ProjectCreate, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if project belongs to user's organization
    if project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this project")

    # Map name to title for update
    project.title = data.title  # ✅ Map name to title
    project.description = data.description
    
    try:
        session.add(project)
        session.commit()
        session.refresh(project)
        
        # Map title back to name for response
        project_data = ProjectRead.model_validate(project)
        project_data.title = project.title
        return project_data
        
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A project with this name may already exist in your organization."
        )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while updating the project."
        )

# ==================================================================
#  ✅ Delete Project (with organization check)
# ================================================================== 
@router.delete("/{project_id}")
def delete_project(
    project_id: int, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if project belongs to user's organization
    if project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this project")

    try:
        session.delete(project)
        session.commit()
        return {"message": "Project deleted successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while deleting the project."
        )