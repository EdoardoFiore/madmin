"""
MADMIN Services Router

API endpoints for systemd service management.
"""
import threading
import time
from fastapi import APIRouter, Depends, HTTPException
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User

from .service import systemd_service

router = APIRouter(prefix="/api/services", tags=["services"])


def _delayed_restart(service_name: str, delay: float = 0.5):
    """Execute restart after a short delay to allow HTTP response to complete."""
    time.sleep(delay)
    systemd_service.restart(service_name)


@router.get("/{service_name}/status")
async def get_service_status(
    service_name: str,
    _user: User = Depends(require_permission("settings.view"))
):
    """
    Get the status of a systemd service.
    
    Only whitelisted services can be queried.
    """
    if not systemd_service.is_allowed(service_name):
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is not in the allowed list"
        )
    
    return systemd_service.get_status(service_name)


@router.post("/{service_name}/restart")
async def restart_service(
    service_name: str,
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Restart a systemd service.
    
    Only whitelisted services can be restarted.
    Requires settings.manage permission.
    
    For self-restart (madmin.service), uses a delayed restart to allow
    the HTTP response to be sent before the service goes down.
    """
    if not systemd_service.is_allowed(service_name):
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is not in the allowed list"
        )
    
    # Normalize service name
    normalized_name = service_name if service_name.endswith('.service') else f"{service_name}.service"
    
    # For self-restart, use delayed restart to allow response to be sent
    if normalized_name == "madmin.service":
        thread = threading.Thread(target=_delayed_restart, args=(service_name, 0.5))
        thread.daemon = True
        thread.start()
        return {"success": True, "message": "Riavvio in corso..."}
    
    # Normal restart for other services
    success, message = systemd_service.restart(service_name)
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}


@router.post("/{service_name}/start")
async def start_service(
    service_name: str,
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Start a systemd service.
    
    Only whitelisted services can be started.
    """
    if not systemd_service.is_allowed(service_name):
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is not in the allowed list"
        )
    
    success, message = systemd_service.start(service_name)
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}


@router.post("/{service_name}/stop")
async def stop_service(
    service_name: str,
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Stop a systemd service.
    
    Only whitelisted services can be stopped.
    """
    if not systemd_service.is_allowed(service_name):
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is not in the allowed list"
        )
    
    success, message = systemd_service.stop(service_name)
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}
