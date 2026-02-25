"""Janitor station message payload schemas."""
from __future__ import annotations

from pydantic import BaseModel


class JanitorPerformTaskPayload(BaseModel):
    task_id: str


class JanitorDismissStickyPayload(BaseModel):
    sticky_id: str
