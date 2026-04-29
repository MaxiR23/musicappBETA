"""Modelos de BugReport."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

BugCategory = Literal["playback", "loading", "ui", "crash", "other"]
BugStatus = Literal["open", "closed"]
BugEntityType = Literal["track", "album", "artist", "playlist"]

class BugReportReporter(BaseModel):
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None

class BugReport(BaseModel):
    id: str
    reporter_id: str
    reporter: BugReportReporter | None = None
    category: BugCategory
    description: str
    entity_type: BugEntityType | None = None
    entity_id: str | None = None
    status: BugStatus = "open"
    created_at: str
    updated_at: str

class BugReportCreate(BaseModel):
    category: BugCategory
    description: str = Field(min_length=5, max_length=2000)
    entity_type: BugEntityType | None = None
    entity_id: str | None = None

class BugReportUpdate(BaseModel):
    status: BugStatus