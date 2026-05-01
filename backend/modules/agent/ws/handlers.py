"""
Dispatch inbound hub→agent command frames to the correct handler.
Each handler returns (success, result_dict, error_str).
"""
import json
import logging

from .protocol import (
    ACTION_SSH_PUSH, ACTION_SSH_REVOKE,
    ACTION_SERVICE_START, ACTION_SERVICE_STOP, ACTION_SERVICE_RESTART,
    ACTION_BACKUP_RUN, ACTION_FIREWALL_RELOAD, ACTION_INFO,
    make_result,
)

logger = logging.getLogger(__name__)


async def dispatch_command(ws, payload: dict):
    """Route a command frame to the right handler and send back command_result."""
    action = payload.get("action", "")
    params = payload.get("params", {})
    correlation_id = payload.get("correlation_id", "")

    logger.info(f"Command received: {action} (correlation={correlation_id})")

    try:
        if action == ACTION_SSH_PUSH:
            success, result, error = await _handle_ssh_push(params)
        elif action == ACTION_SSH_REVOKE:
            success, result, error = await _handle_ssh_revoke(params)
        elif action in (ACTION_SERVICE_START, ACTION_SERVICE_STOP, ACTION_SERVICE_RESTART):
            success, result, error = await _handle_service(action, params)
        elif action == ACTION_BACKUP_RUN:
            success, result, error = await _handle_backup(params)
        elif action == ACTION_FIREWALL_RELOAD:
            success, result, error = await _handle_firewall_reload(params)
        elif action == ACTION_INFO:
            success, result, error = await _handle_info(params)
        else:
            success, result, error = False, None, f"Unknown action: {action}"
    except Exception as e:
        logger.exception(f"Handler error for {action}: {e}")
        success, result, error = False, None, str(e)

    frame = make_result(correlation_id, success, result, error)
    try:
        await ws.send(json.dumps(frame))
    except Exception as e:
        logger.error(f"Failed to send command_result: {e}")

    # Audit log
    from modules.agent.ws.client import _log_event
    level = "info" if success else "warning"
    await _log_event(
        f"command_{action.replace('.', '_')}",
        level,
        error or json.dumps(result)[:200] if result else None,
    )


async def _handle_ssh_push(params: dict):
    from modules.agent.service.ssh import push_key
    assignment_id = params.get("assignment_id", "")
    public_key = params.get("public_key", "")
    target_user = params.get("target_user", "madmin")
    allow_source_ips = params.get("allow_source_ips", [])
    expires_at = params.get("expires_at")

    if not assignment_id or not public_key:
        return False, None, "Missing assignment_id or public_key"

    ok, msg = await push_key(
        assignment_id=assignment_id,
        public_key=public_key,
        target_user=target_user,
        allow_source_ips=allow_source_ips,
        expires_at=expires_at,
    )
    return ok, {"message": msg}, None if ok else msg


async def _handle_ssh_revoke(params: dict):
    from modules.agent.service.ssh import revoke_key
    assignment_id = params.get("assignment_id", "")
    if not assignment_id:
        return False, None, "Missing assignment_id"
    ok, msg = await revoke_key(assignment_id)
    return ok, {"message": msg}, None if ok else msg


async def _handle_service(action: str, params: dict):
    from modules.agent.service.ops import service_action
    service_name = params.get("service")
    if not service_name:
        return False, None, "Missing service name"
    op = action.split(".")[-1]  # start | stop | restart
    ok, msg = await service_action(service_name, op)
    return ok, {"message": msg}, None if ok else msg


async def _handle_backup(params: dict):
    from modules.agent.service.ops import run_backup
    ok, result = await run_backup(params)
    return ok, result, None if ok else result.get("error")


async def _handle_firewall_reload(params: dict):
    from modules.agent.service.ops import reload_firewall
    ok, msg = await reload_firewall()
    return ok, {"message": msg}, None if ok else msg


async def _handle_info(params: dict):
    from modules.agent.service.heartbeat import collect_telemetry_batch
    data = await collect_telemetry_batch()
    return True, data, None
