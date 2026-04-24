"""
MADMIN Crontab Router

API endpoints for crontab management.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.auth.dependencies import require_permission
from core.auth.models import User

from .service import cron_service

router = APIRouter(prefix="/api/cron", tags=["Cron"])


# ── Request/Response Models ────────────────────────────────────────────

class CronEntryCreate(BaseModel):
    schedule: str
    command: str


class CronEntryToggle(BaseModel):
    enabled: bool


class CronEntryItem(BaseModel):
    id: int
    schedule: str
    command: str
    enabled: bool
    description: Optional[str] = None


class CronPreset(BaseModel):
    label: str
    value: str


class CronListResponse(BaseModel):
    user: str
    entries: List[CronEntryItem]
    presets: List[CronPreset]


class CronActionResponse(BaseModel):
    success: bool
    message: str


class CronValidateResponse(BaseModel):
    schedule: str
    valid: bool
    description: Optional[str] = None


@router.get("/entries", response_model=CronListResponse)
async def list_cron_entries(
    user: str = "root",
    _user: User = Depends(require_permission("settings.view"))
):
    """
    List all crontab entries for a system user.
    """
    success, entries = cron_service.get_crontab(user)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to read crontab")
    
    # Add human-readable descriptions
    for entry in entries:
        if entry.get("schedule"):
            entry["description"] = cron_service.describe_schedule(entry["schedule"])
    
    return {
        "user": user,
        "entries": entries,
        "presets": [{"label": k, "value": v} for k, v in cron_service.PRESETS.items()]
    }


@router.post("/entries", response_model=CronActionResponse)
async def add_cron_entry(
    data: CronEntryCreate,
    user: str = "root",
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Add a new crontab entry.
    """
    if not cron_service.validate_schedule(data.schedule):
        raise HTTPException(status_code=400, detail="Invalid cron schedule")
    
    success, message = cron_service.add_entry(data.schedule, data.command, user)
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}


@router.delete("/entries/{entry_id}", response_model=CronActionResponse)
async def delete_cron_entry(
    entry_id: int,
    user: str = "root",
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Delete a crontab entry.
    """
    success, message = cron_service.delete_entry(entry_id, user)
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}


@router.patch("/entries/{entry_id}/toggle", response_model=CronActionResponse)
async def toggle_cron_entry(
    entry_id: int,
    user: str = "root",
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Toggle enabled/disabled state of a crontab entry.
    """
    success, message = cron_service.toggle_entry(entry_id, user)
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}


@router.get("/validate", response_model=CronValidateResponse)
async def validate_schedule(
    schedule: str,
    _user: User = Depends(require_permission("settings.view"))
):
    """
    Validate a cron schedule expression and return description.
    """
    valid = cron_service.validate_schedule(schedule)
    description = cron_service.describe_schedule(schedule) if valid else None
    
    return {
        "schedule": schedule,
        "valid": valid,
        "description": description
    }
