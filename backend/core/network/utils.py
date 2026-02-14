import subprocess
import logging
import urllib.request
import re
from typing import Optional

logger = logging.getLogger(__name__)

def get_public_ip() -> Optional[str]:
    """
    Get the server's public IP address.
    Tries multiple services for reliability.
    """
    services = [
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
        "https://ipecho.net/plain"
    ]
    
    for url in services:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                ip = response.read().decode('utf-8').strip()
                # Basic validation
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                    return ip
        except Exception as e:
            logger.debug(f"Failed to get IP from {url}: {e}")
            continue
            
    return None

def get_default_interface() -> Optional[str]:
    """
    Get the default network interface name.
    Parses 'ip route show default'.
    """
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout:
            # Output format: "default via 1.2.3.4 dev eth0 ..."
            parts = result.stdout.strip().split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return None
    except Exception as e:
        logger.error(f"Failed to get default interface: {e}")
        return None
