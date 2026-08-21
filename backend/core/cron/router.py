"""
MADMIN Crontab Router

API endpoints for crontab management.

Scheduling a job means running a command as root, which no delegable permission
can safely grant — so writes require superuser and the command must be a script
that already exists in the configured scripts directory. `cron.view` covers the
read-only side.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.auth.dependencies import require_permission, require_superuser
from core.auth.models import User

from .service import cron_service

router = APIRouter(prefix="/api/cron", tags=["Cron"])


# ── Request/Response Models ────────────────────────────────────────────

class CronEntryCreate(BaseModel):
    schedule: str
    script: str                  # filename inside the scripts directory
    args: List[str] = []


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


class CronScriptItem(BaseModel):
    name: str
    size: int
    modified: str
    description: Optional[str] = None


class CronScriptContent(BaseModel):
    name: str
    content: str


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


# ── Scripts ────────────────────────────────────────────────────────────

@router.get("/scripts", response_model=List[CronScriptItem])
async def list_cron_scripts(
    _user: User = Depends(require_permission("cron.view"))
):
    """
    List the scripts a job may run.

    The directory is populated out of band by an operator with shell access;
    MADMIN never writes to it.
    """
    return cron_service.list_scripts()


@router.get("/scripts/{name}", response_model=CronScriptContent)
async def get_cron_script(
    name: str,
    _user: User = Depends(require_permission("cron.view"))
):
    """Read a script's contents (read-only — there is no write counterpart)."""
    try:
        return {"name": name, "content": cron_service.read_script(name)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to read script")


# ── Entries ────────────────────────────────────────────────────────────

@router.get("/entries", response_model=CronListResponse)
async def list_cron_entries(
    _user: User = Depends(require_permission("cron.view"))
):
    """
    List root's crontab entries.
    """
    success, entries = cron_service.get_crontab()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to read crontab")

    # Add human-readable descriptions
    for entry in entries:
        if entry.get("schedule"):
            entry["description"] = cron_service.describe_schedule(entry["schedule"])

    return {
        "user": "root",
        "entries": entries,
        "presets": [{"label": k, "value": v} for k, v in cron_service.PRESETS.items()]
    }


@router.post("/entries", response_model=CronActionResponse)
async def add_cron_entry(
    data: CronEntryCreate,
    _user: User = Depends(require_superuser())
):
    """
    Schedule an allowlisted script. Superuser only — the job runs as root.
    """
    if not cron_service.validate_schedule(data.schedule):
        raise HTTPException(status_code=400, detail="Invalid cron schedule")

    try:
        success, message = cron_service.add_entry(data.schedule, data.script, data.args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=500, detail=message)

    return {"success": True, "message": message}


@router.put("/entries/{entry_id}", response_model=CronActionResponse)
async def update_cron_entry(
    entry_id: int,
    data: CronEntryCreate,
    _user: User = Depends(require_superuser())
):
    """
    Change an existing job's schedule or command. Superuser only.
    """
    if not cron_service.validate_schedule(data.schedule):
        raise HTTPException(status_code=400, detail="Invalid cron schedule")

    try:
        success, message = cron_service.update_entry(
            entry_id, data.schedule, data.script, data.args
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.delete("/entries/{entry_id}", response_model=CronActionResponse)
async def delete_cron_entry(
    entry_id: int,
    _user: User = Depends(require_superuser())
):
    """
    Delete a crontab entry. Superuser only.
    """
    success, message = cron_service.delete_entry(entry_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.patch("/entries/{entry_id}/toggle", response_model=CronActionResponse)
async def toggle_cron_entry(
    entry_id: int,
    _user: User = Depends(require_superuser())
):
    """
    Enable or disable a crontab entry. Superuser only.
    """
    success, message = cron_service.toggle_entry(entry_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.get("/validate", response_model=CronValidateResponse)
async def validate_schedule(
    schedule: str,
    _user: User = Depends(require_permission("cron.view"))
):
    """
    Validate a cron schedule expression and describe it.
    """
    valid = cron_service.validate_schedule(schedule)
    return {
        "schedule": schedule,
        "valid": valid,
        "description": cron_service.describe_schedule(schedule) if valid else None
    }
