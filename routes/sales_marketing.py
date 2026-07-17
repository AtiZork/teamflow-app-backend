from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlmodel import Session, select

from core.database import get_session
from core.security import get_current_admin, get_current_user
from models.models import PipelineStage, SalesPipelineItem, User, UserRole
from schemas.sales_marketing_schema import (
    SalesPipelineCreate,
    SalesPipelineRead,
    SalesPipelineReport,
    SalesPipelineUpdate,
    SalesReportBucket,
)

router = APIRouter(prefix="/sales-marketing", tags=["Sales & Marketing"])


def _is_admin(user: User) -> bool:
    return user.role in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]


def _get_pipeline_item(item_id: int, session: Session, current_user: User) -> SalesPipelineItem:
    item = session.get(SalesPipelineItem, item_id)
    if not item or item.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Pipeline item not found")
    return item


def _validate_assignee(session: Session, organization_id: int, assigned_to_id: Optional[int]) -> None:
    if assigned_to_id is None:
        return
    assignee = session.get(User, assigned_to_id)
    if not assignee or assignee.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="Assigned user must belong to your organization")


def _user_names(session: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    users = session.exec(select(User).where(User.id.in_(user_ids))).all()
    return {user.id: user.full_name for user in users if user.id is not None}


def _serialize_items(items: List[SalesPipelineItem], session: Session) -> List[SalesPipelineRead]:
    user_ids = {item.created_by_id for item in items}
    user_ids.update(item.assigned_to_id for item in items if item.assigned_to_id)
    names = _user_names(session, user_ids)

    return [
        SalesPipelineRead(
            **item.model_dump(),
            created_by_name=names.get(item.created_by_id),
            assigned_to_name=names.get(item.assigned_to_id) if item.assigned_to_id else None,
        )
        for item in items
    ]


@router.get("/pipeline", response_model=List[SalesPipelineRead])
def list_pipeline_items(
    stage: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    hierarchy_level: Optional[str] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    query = select(SalesPipelineItem).where(
        SalesPipelineItem.organization_id == current_user.organization_id
    )

    if stage:
        query = query.where(SalesPipelineItem.stage == stage)
    if department:
        query = query.where(SalesPipelineItem.department == department)
    if source:
        query = query.where(SalesPipelineItem.source == source)
    if hierarchy_level:
        query = query.where(SalesPipelineItem.hierarchy_level == hierarchy_level)
    if assigned_to_id:
        query = query.where(SalesPipelineItem.assigned_to_id == assigned_to_id)
    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                SalesPipelineItem.prospect_name.ilike(term),
                SalesPipelineItem.company_name.ilike(term),
                SalesPipelineItem.deal_title.ilike(term),
                SalesPipelineItem.external_account.ilike(term),
                SalesPipelineItem.notes.ilike(term),
            )
        )

    query = query.order_by(SalesPipelineItem.updated_at.desc()).offset(offset).limit(limit)
    items = session.exec(query).all()
    return _serialize_items(items, session)


@router.post("/pipeline", response_model=SalesPipelineRead, status_code=status.HTTP_201_CREATED)
def create_pipeline_item(
    payload: SalesPipelineCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _validate_assignee(session, current_user.organization_id, payload.assigned_to_id)

    data = payload.model_dump()
    assigned_to_id = data.pop("assigned_to_id", None) or current_user.id

    item = SalesPipelineItem(
        **data,
        organization_id=current_user.organization_id,
        created_by_id=current_user.id,
        assigned_to_id=assigned_to_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize_items([item], session)[0]


@router.get("/pipeline/{item_id}", response_model=SalesPipelineRead)
def get_pipeline_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = _get_pipeline_item(item_id, session, current_user)
    return _serialize_items([item], session)[0]


@router.put("/pipeline/{item_id}", response_model=SalesPipelineRead)
def update_pipeline_item(
    item_id: int,
    payload: SalesPipelineUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = _get_pipeline_item(item_id, session, current_user)

    if not _is_admin(current_user) and item.assigned_to_id != current_user.id and item.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only update pipeline items assigned to you")

    updates = payload.model_dump(exclude_unset=True)
    _validate_assignee(session, current_user.organization_id, updates.get("assigned_to_id"))

    for field, value in updates.items():
        setattr(item, field, value)
    item.updated_at = datetime.utcnow()

    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize_items([item], session)[0]


@router.delete("/pipeline/{item_id}", status_code=status.HTTP_200_OK)
def delete_pipeline_item(
    item_id: int,
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    item = _get_pipeline_item(item_id, session, current_user)
    session.delete(item)
    session.commit()
    return {"message": "Pipeline item deleted"}


def _bucket(items: List[SalesPipelineItem], field: str) -> List[SalesReportBucket]:
    buckets: dict[str, dict[str, float]] = {}
    for item in items:
        key = getattr(item, field) or "unknown"
        if key not in buckets:
            buckets[key] = {"count": 0, "value": 0.0}
        buckets[key]["count"] += 1
        buckets[key]["value"] += float(item.estimated_value or 0)

    return [
        SalesReportBucket(key=key, count=int(data["count"]), value=round(data["value"], 2))
        for key, data in sorted(buckets.items(), key=lambda entry: entry[0])
    ]


@router.get("/reports/summary", response_model=SalesPipelineReport)
def get_pipeline_report(
    current_user: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    now = datetime.utcnow()
    items = session.exec(
        select(SalesPipelineItem)
        .where(SalesPipelineItem.organization_id == current_user.organization_id)
        .order_by(SalesPipelineItem.updated_at.desc())
    ).all()

    open_stages = {stage.value for stage in PipelineStage if stage not in [PipelineStage.WON, PipelineStage.LOST]}
    open_items = [item for item in items if item.stage in open_stages]
    won_items = [item for item in items if item.stage == PipelineStage.WON.value]
    lost_items = [item for item in items if item.stage == PipelineStage.LOST.value]
    overdue_followups = [
        item for item in open_items if item.next_follow_up and item.next_follow_up < now
    ]

    total_value = sum(float(item.estimated_value or 0) for item in open_items)
    weighted_value = sum(
        float(item.estimated_value or 0) * (float(item.probability or 0) / 100)
        for item in open_items
    )
    upcoming = [
        item for item in open_items if item.next_follow_up and item.next_follow_up >= now
    ][:5]

    return SalesPipelineReport(
        total_items=len(items),
        open_items=len(open_items),
        won_items=len(won_items),
        lost_items=len(lost_items),
        overdue_followups=len(overdue_followups),
        total_estimated_value=round(total_value, 2),
        weighted_pipeline_value=round(weighted_value, 2),
        by_stage=_bucket(items, "stage"),
        by_source=_bucket(items, "source"),
        by_department=_bucket(items, "department"),
        by_hierarchy_level=_bucket(items, "hierarchy_level"),
        upcoming_followups=_serialize_items(upcoming, session),
        recent_items=_serialize_items(items[:5], session),
    )
