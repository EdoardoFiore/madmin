"""
MADMIN Systemd Service Manager

Provides systemd service control (start, stop, restart, status).
Limited to whitelisted services for security.
"""
import subprocess
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class SystemdService:
    """Service class for systemd operations."""
    
    # Whitelist of allowed services for security
    ALLOWED_SERVICES = [
        "madmin.service",
    ]
    
    @staticmethod
    def is_allowed(service_name: str) -> bool:
        """Check if service is in the whitelist."""
        # Normalize service name
        if not service_name.endswith('.service'):
            service_name = f"{service_name}.service"
        return service_name in SystemdService.ALLOWED_SERVICES
    
    @staticmethod
    def _run_systemctl(action: str, service: str) -> tuple[bool, str]:
        """
        Execute a systemctl command.
        
        Args:
            action: The action (start, stop, restart, status)
            service: The service name
            
        Returns:
            Tuple of (success, message)
        """
        # Normalize service name
        if not service.endswith('.service'):
            service = f"{service}.service"
        
        try:
            result = subprocess.run(
                ['systemctl', action, service],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return True, f"Service {service} {action} successful"
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return False, f"Failed to {action} {service}: {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, f"Timeout while executing {action} on {service}"
        except FileNotFoundError:
            return False, "systemctl not found. This feature requires Linux with systemd."
        except Exception as e:
            logger.error(f"Error executing systemctl {action} {service}: {e}")
            return False, str(e)
    
    @staticmethod
    def get_status(service: str) -> dict:
        """
        Get the status of a systemd service.
        
        Returns:
            Dict with status info
        """
        if not service.endswith('.service'):
            service = f"{service}.service"
        
        try:
            # Check if active
            active_result = subprocess.run(
                ['systemctl', 'is-active', service],
                capture_output=True,
                text=True,
                timeout=10
            )
            is_active = active_result.stdout.strip() == 'active'
            
            # Check if enabled
            enabled_result = subprocess.run(
                ['systemctl', 'is-enabled', service],
                capture_output=True,
                text=True,
                timeout=10
            )
            is_enabled = enabled_result.stdout.strip() == 'enabled'
            
            return {
                "service": service,
                "active": is_active,
                "status": active_result.stdout.strip(),
                "enabled": is_enabled
            }
            
        except FileNotFoundError:
            return {
                "service": service,
                "active": False,
                "status": "unknown",
                "enabled": False,
                "error": "systemctl not found"
            }
        except Exception as e:
            return {
                "service": service,
                "active": False,
                "status": "error",
                "enabled": False,
                "error": str(e)
            }
    
    @staticmethod
    def restart(service: str) -> tuple[bool, str]:
        """Restart a systemd service."""
        return SystemdService._run_systemctl('restart', service)
    
    @staticmethod
    def start(service: str) -> tuple[bool, str]:
        """Start a systemd service."""
        return SystemdService._run_systemctl('start', service)
    
    @staticmethod
    def stop(service: str) -> tuple[bool, str]:
        """Stop a systemd service."""
        return SystemdService._run_systemctl('stop', service)


systemd_service = SystemdService()
