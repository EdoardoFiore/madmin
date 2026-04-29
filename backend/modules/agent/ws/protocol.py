"""
WS frame type constants and payload helpers.
Mirrors hub/ws/protocol.py — keep in sync.
"""
FRAME_HEARTBEAT = "heartbeat"
FRAME_COMMAND = "command"
FRAME_COMMAND_RESULT = "command_result"
FRAME_EVENT = "event"
FRAME_CONFIG_UPDATE = "config_update"
FRAME_PING = "ping"
FRAME_PONG = "pong"

# Command actions (hub → agent)
ACTION_SSH_PUSH = "ssh.push"
ACTION_SSH_REVOKE = "ssh.revoke"
ACTION_SERVICE_START = "service.start"
ACTION_SERVICE_STOP = "service.stop"
ACTION_SERVICE_RESTART = "service.restart"
ACTION_BACKUP_RUN = "backup.run"
ACTION_FIREWALL_RELOAD = "firewall.reload"
ACTION_INFO = "info"


def make_result(correlation_id: str, success: bool, result=None, error: str = None) -> dict:
    return {
        "type": FRAME_COMMAND_RESULT,
        "payload": {
            "correlation_id": correlation_id,
            "success": success,
            "result": result,
            "error": error,
        },
    }


def make_heartbeat(payload: dict) -> dict:
    return {"type": FRAME_HEARTBEAT, "payload": payload}


def make_event(event_type: str, severity: str = "info", message: str = "", data: dict = None) -> dict:
    return {
        "type": FRAME_EVENT,
        "payload": {
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "data": data or {},
        },
    }
