# project_schema.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    # organization_id and creator_id are set server-side


class ProjectRead(BaseModel):
    id: int
    title: str = Field(..., max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    creator_id: int
    created_at: datetime
    organization_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
