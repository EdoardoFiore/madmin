"""
MADMIN Network Service

Provides network interface information using psutil and netplan management.
"""
import logging
import subprocess
import os
import glob
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not installed. Network stats will be unavailable.")

# Try to import yaml
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("PyYAML not installed. Netplan management will be unavailable.")

NETPLAN_DIR = "/etc/netplan"


class NetworkService:
    """Service class for network interface information."""
    
    @staticmethod
    def get_interfaces() -> List[Dict]:
        """
        Get all network interfaces with their details.
        
        Returns:
            List of dicts with interface info: name, addresses, mac, status, stats
        """
        if not PSUTIL_AVAILABLE:
            return []
        
        interfaces = []
        
        try:
            # Get interface addresses
            if_addrs = psutil.net_if_addrs()
            
            # Get interface stats
            if_stats = psutil.net_if_stats()
            
            # Get IO counters
            io_counters = psutil.net_io_counters(pernic=True)
            
            # Get netplan configs for each interface
            netplan_configs = NetplanService.get_all_interface_configs()
            
            for iface_name, addrs in if_addrs.items():
                # Skip loopback interface
                if iface_name == 'lo':
                    continue
                    
                iface_info = {
                    "name": iface_name,
                    "ipv4": None,
                    "ipv6": None,
                    "mac": None,
                    "is_up": False,
                    "speed": 0,
                    "mtu": 0,
                    "bytes_sent": 0,
                    "bytes_recv": 0,
                    "packets_sent": 0,
                    "packets_recv": 0,
                    "errors_in": 0,
                    "errors_out": 0,
                    "netplan": netplan_configs.get(iface_name)
                }
                
                # Parse addresses
                for addr in addrs:
                    if addr.family.name == 'AF_INET':
                        iface_info["ipv4"] = addr.address
                        iface_info["netmask"] = addr.netmask
                    elif addr.family.name == 'AF_INET6':
                        # Skip link-local IPv6
                        if not addr.address.startswith('fe80::'):
                            iface_info["ipv6"] = addr.address
                    elif addr.family.name == 'AF_LINK' or addr.family.name == 'AF_PACKET':
                        iface_info["mac"] = addr.address
                
                # Get stats if available
                if iface_name in if_stats:
                    stats = if_stats[iface_name]
                    iface_info["is_up"] = stats.isup
                    iface_info["speed"] = stats.speed  # Mbps
                    iface_info["mtu"] = stats.mtu
                
                # Get IO counters if available
                if iface_name in io_counters:
                    io = io_counters[iface_name]
                    iface_info["bytes_sent"] = io.bytes_sent
                    iface_info["bytes_recv"] = io.bytes_recv
                    iface_info["packets_sent"] = io.packets_sent
                    iface_info["packets_recv"] = io.packets_recv
                    iface_info["errors_in"] = io.errin
                    iface_info["errors_out"] = io.errout
                
                interfaces.append(iface_info)
            
            # Sort: up interfaces first, then by name
            interfaces.sort(key=lambda x: (not x['is_up'], x['name']))
            
        except Exception as e:
            logger.error(f"Error getting network interfaces: {e}")
        
        return interfaces
    
    @staticmethod
    def format_bytes(bytes_value: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.1f} PB"


class NetplanService:
    """Service class for netplan configuration management."""
    
    @staticmethod
    def get_netplan_files() -> List[str]:
        """Get list of netplan YAML files."""
        pattern = os.path.join(NETPLAN_DIR, "*.yaml")
        return sorted(glob.glob(pattern))
    
    @staticmethod
    def read_netplan_config() -> Dict:
        """
        Read and merge all netplan configurations.
        
        Returns:
            Merged netplan configuration dict
        """
        if not YAML_AVAILABLE:
            return {}
        
        merged = {"network": {"version": 2, "ethernets": {}}}
        
        for filepath in NetplanService.get_netplan_files():
            try:
                with open(filepath, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    
                if "network" in config:
                    net = config["network"]
                    if "ethernets" in net:
                        merged["network"]["ethernets"].update(net["ethernets"])
                    if "renderer" in net:
                        merged["network"]["renderer"] = net["renderer"]
                        
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
        
        return merged
    
    @staticmethod
    def get_all_interface_configs() -> Dict[str, Dict]:
        """
        Get netplan config for all interfaces.
        
        Returns:
            Dict mapping interface name to its config
        """
        config = NetplanService.read_netplan_config()
        ethernets = config.get("network", {}).get("ethernets", {})
        
        result = {}
        for iface_name, iface_config in ethernets.items():
            result[iface_name] = NetplanService._parse_interface_config(iface_config)
        
        return result
    
    @staticmethod
    def _parse_interface_config(config: Dict) -> Dict:
        """Parse netplan interface config into simplified format."""
        result = {
            "dhcp4": config.get("dhcp4", False),
            "dhcp6": config.get("dhcp6", False),
            "addresses": config.get("addresses", []),
            "gateway4": None,
            "dns_servers": [],
            "dns_search": [],
            "mtu": config.get("mtu"),
            "optional": config.get("optional", False)
        }
        
        # Handle routes for gateway
        routes = config.get("routes", [])
        for route in routes:
            if route.get("to") == "default" or route.get("to") == "0.0.0.0/0":
                result["gateway4"] = route.get("via")
                break
        
        # Legacy gateway4 field
        if not result["gateway4"] and "gateway4" in config:
            result["gateway4"] = config["gateway4"]
        
        # DNS nameservers
        nameservers = config.get("nameservers", {})
        result["dns_servers"] = nameservers.get("addresses", [])
        result["dns_search"] = nameservers.get("search", [])
        
        return result
    
    @staticmethod
    def get_interface_config(interface: str) -> Optional[Dict]:
        """Get netplan config for a specific interface."""
        configs = NetplanService.get_all_interface_configs()
        return configs.get(interface)
    
    @staticmethod
    def set_interface_config(
        interface: str,
        dhcp4: bool = True,
        addresses: List[str] = None,
        gateway: str = None,
        dns_servers: List[str] = None,
        mtu: int = None
    ) -> Tuple[bool, str]:
        """
        Set netplan config for an interface.
        
        Creates/updates 99-madmin-{interface}.yaml in /etc/netplan/
        
        Args:
            interface: Interface name (e.g., "eth0")
            dhcp4: Use DHCP for IPv4
            addresses: List of addresses with CIDR (e.g., ["192.168.1.100/24"])
            gateway: Default gateway IP
            dns_servers: List of DNS server IPs
            mtu: MTU value
            
        Returns:
            Tuple of (success, message)
        """
        if not YAML_AVAILABLE:
            return False, "PyYAML not installed"
        
        # Build interface config
        iface_config = {}
        
        if dhcp4:
            iface_config["dhcp4"] = True
        else:
            iface_config["dhcp4"] = False
            
            if addresses:
                iface_config["addresses"] = addresses
            
            if gateway:
                iface_config["routes"] = [{"to": "default", "via": gateway}]
            
            if dns_servers:
                iface_config["nameservers"] = {"addresses": dns_servers}
        
        if mtu:
            iface_config["mtu"] = mtu
        
        # Build netplan config
        config = {
            "network": {
                "version": 2,
                "ethernets": {
                    interface: iface_config
                }
            }
        }
        
        # Write to file
        filename = f"99-madmin-{interface}.yaml"
        filepath = os.path.join(NETPLAN_DIR, filename)
        
        try:
            with open(filepath, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            # Set correct permissions
            os.chmod(filepath, 0o600)
            
            logger.info(f"Wrote netplan config to {filepath}")
            return True, f"Configuration saved to {filename}"
            
        except PermissionError:
            return False, "Permission denied. Run as root."
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def apply_netplan() -> Tuple[bool, str]:
        """
        Apply netplan configuration.
        
        Returns:
            Tuple of (success, output/error message)
        """
        try:
            # First try netplan try (safer, with rollback)
            result = subprocess.run(
                ["netplan", "apply"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"netplan apply failed: {result.stderr}"
            
            return True, "Configuration applied successfully"
            
        except subprocess.TimeoutExpired:
            return False, "netplan apply timed out"
        except FileNotFoundError:
            return False, "netplan command not found"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def delete_interface_config(interface: str) -> Tuple[bool, str]:
        """
        Delete MADMIN-managed netplan config for an interface.
        
        Only deletes 99-madmin-{interface}.yaml files.
        
        Returns:
            Tuple of (success, message)
        """
        filename = f"99-madmin-{interface}.yaml"
        filepath = os.path.join(NETPLAN_DIR, filename)
        
        if not os.path.exists(filepath):
            return False, f"No MADMIN config found for {interface}"
        
        try:
            os.remove(filepath)
            logger.info(f"Deleted netplan config {filepath}")
            return True, f"Deleted {filename}"
        except PermissionError:
            return False, "Permission denied"
        except Exception as e:
            return False, str(e)


network_service = NetworkService()
netplan_service = NetplanService()

