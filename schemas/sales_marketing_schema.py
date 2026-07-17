from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.models import (
    PipelinePriority,
    PipelineSource,
    PipelineStage,
    SalesDepartment,
    SalesHierarchyLevel,
)


class SalesPipelineBase(BaseModel):
    department: str = Field(default=SalesDepartment.SALES.value)
    hierarchy_level: str = Field(default=SalesHierarchyLevel.EXECUTIVE.value)
    source: str = Field(default=PipelineSource.UPWORK.value)
    stage: str = Field(default=PipelineStage.NEW.value)
    priority: str = Field(default=PipelinePriority.MEDIUM.value)

    prospect_name: str = Field(..., min_length=1, max_length=150)
    company_name: Optional[str] = Field(default=None, max_length=150)
    profile_url: Optional[str] = Field(default=None, max_length=500)
    external_account: Optional[str] = Field(default=None, max_length=150)
    deal_title: Optional[str] = Field(default=None, max_length=200)
    estimated_value: float = Field(default=0.0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    probability: int = Field(default=0, ge=0, le=100)

    next_follow_up: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None
    notes: Optional[str] = None
    tags: Optional[str] = Field(default=None, max_length=500)
    assigned_to_id: Optional[int] = None

    @field_validator("department")
    @classmethod
    def validate_department(cls, value: str) -> str:
        allowed = {item.value for item in SalesDepartment}
        if value not in allowed:
            raise ValueError(f"department must be one of: {', '.join(sorted(allowed))}")
        return value

    @field_validator("hierarchy_level")
    @classmethod
    def validate_hierarchy_level(cls, value: str) -> str:
        allowed = {item.value for item in SalesHierarchyLevel}
        if value not in allowed:
            raise ValueError(f"hierarchy_level must be one of: {', '.join(sorted(allowed))}")
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        allowed = {item.value for item in PipelineSource}
        if value not in allowed:
            raise ValueError(f"source must be one of: {', '.join(sorted(allowed))}")
        return value

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        allowed = {item.value for item in PipelineStage}
        if value not in allowed:
            raise ValueError(f"stage must be one of: {', '.join(sorted(allowed))}")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        allowed = {item.value for item in PipelinePriority}
        if value not in allowed:
            raise ValueError(f"priority must be one of: {', '.join(sorted(allowed))}")
        return value


class SalesPipelineCreate(SalesPipelineBase):
    pass


class SalesPipelineUpdate(BaseModel):
    department: Optional[str] = None
    hierarchy_level: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    priority: Optional[str] = None
    prospect_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    company_name: Optional[str] = Field(default=None, max_length=150)
    profile_url: Optional[str] = Field(default=None, max_length=500)
    external_account: Optional[str] = Field(default=None, max_length=150)
    deal_title: Optional[str] = Field(default=None, max_length=200)
    estimated_value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    probability: Optional[int] = Field(default=None, ge=0, le=100)
    next_follow_up: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None
    notes: Optional[str] = None
    tags: Optional[str] = Field(default=None, max_length=500)
    assigned_to_id: Optional[int] = None


class SalesPipelineRead(SalesPipelineBase):
    id: int
    organization_id: int
    created_by_id: int
    created_by_name: Optional[str] = None
    assigned_to_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SalesReportBucket(BaseModel):
    key: str
    count: int
    value: float


class SalesPipelineReport(BaseModel):
    total_items: int
    open_items: int
    won_items: int
    lost_items: int
    overdue_followups: int
    total_estimated_value: float
    weighted_pipeline_value: float
    by_stage: List[SalesReportBucket]
    by_source: List[SalesReportBucket]
    by_department: List[SalesReportBucket]
    by_hierarchy_level: List[SalesReportBucket]
    upcoming_followups: List[SalesPipelineRead]
    recent_items: List[SalesPipelineRead]
