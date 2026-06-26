"""
OpenVPN Module - Service Layer

Business logic for OpenVPN operations: PKI management, config generation,
interface control, IP allocation, CCD management, and firewall rules.
"""
import subprocess
import logging
import re
import shutil
import urllib.request
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from ipaddress import IPv4Network
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .models import OvpnInstance, OvpnClient
from core.network.utils import get_public_ip, get_default_interface
from core.firewall import iptables as core_iptables

logger = logging.getLogger(__name__)

# Paths
OPENVPN_BASE_DIR = Path("/etc/openvpn/server")
OPENVPN_CLIENT_DIR = Path("/etc/openvpn/client")
EASYRSA_SOURCE = Path("/usr/share/easy-rsa")


class OpenVPNService:
    """Service class for OpenVPN operations."""
    
    # Firewall chain names
    OVPN_INPUT_CHAIN = "MOD_OVPN_INPUT"
    OVPN_FORWARD_CHAIN = "MOD_OVPN_FORWARD"
    OVPN_NAT_CHAIN = "MOD_OVPN_NAT"
    
    # =========================================================================
    # PKI MANAGEMENT
    # =========================================================================
    
    @staticmethod
    def get_instance_dir(instance_id: str) -> Path:
        """Get the directory for an instance."""
        return OPENVPN_BASE_DIR / instance_id
    
    @staticmethod
    def get_easyrsa_dir(instance_id: str) -> Path:
        """Get the easy-rsa directory for an instance."""
        return OpenVPNService.get_instance_dir(instance_id) / "easy-rsa"
    
    @staticmethod
    def get_ccd_dir(instance_id: str) -> Path:
        """Get the CCD directory for an instance."""
        return OpenVPNService.get_instance_dir(instance_id) / "ccd"
    
    @staticmethod
    def init_pki(instance_id: str) -> bool:
        """Initialize PKI for a new instance."""
        instance_dir = OpenVPNService.get_instance_dir(instance_id)
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        ccd_dir = OpenVPNService.get_ccd_dir(instance_id)
        
        try:
            # Create directories
            instance_dir.mkdir(parents=True, exist_ok=True)
            ccd_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy easy-rsa
            if easyrsa_dir.exists():
                shutil.rmtree(easyrsa_dir)
            shutil.copytree(EASYRSA_SOURCE, easyrsa_dir)
            
            # Initialize PKI
            subprocess.run(
                ["./easyrsa", "init-pki"],
                cwd=easyrsa_dir,
                check=True,
                capture_output=True
            )
            
            logger.info(f"PKI initialized for instance {instance_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to init PKI for {instance_id}: {e}")
            return False
    
    @staticmethod
    def build_ca(instance_id: str, cn: str = "MADMIN OpenVPN CA", days: int = 3650) -> Dict:
        """Build Certificate Authority."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        
        try:
            # Set environment for non-interactive
            env = {
                "EASYRSA_BATCH": "1",
                "EASYRSA_REQ_CN": cn,
                "EASYRSA_CA_EXPIRE": str(days),
            }
            
            subprocess.run(
                ["./easyrsa", "--batch", f"--days={days}", "build-ca", "nopass"],
                cwd=easyrsa_dir,
                env={**subprocess.os.environ, **env},
                check=True,
                capture_output=True
            )
            
            # Read CA cert
            ca_cert_path = easyrsa_dir / "pki" / "ca.crt"
            expiry = OpenVPNService._parse_cert_expiry(ca_cert_path)
            
            logger.info(f"CA built for instance {instance_id}")
            return {
                "success": True,
                "ca_cert": ca_cert_path.read_text(),
                "expiry": expiry
            }
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to build CA: {e.stderr.decode()}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def generate_server_cert(instance_id: str, days: int = 3650) -> Dict:
        """Generate server certificate."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        server_name = f"server_{instance_id}"
        
        try:
            # Generate server keypair and cert
            subprocess.run(
                ["./easyrsa", "--batch", f"--days={days}", 
                 "build-server-full", server_name, "nopass"],
                cwd=easyrsa_dir,
                check=True,
                capture_output=True
            )
            
            # Read cert and key
            cert_path = easyrsa_dir / "pki" / "issued" / f"{server_name}.crt"
            key_path = easyrsa_dir / "pki" / "private" / f"{server_name}.key"
            
            # Copy to instance directory
            instance_dir = OpenVPNService.get_instance_dir(instance_id)
            shutil.copy(cert_path, instance_dir / "server.crt")
            shutil.copy(key_path, instance_dir / "server.key")
            shutil.copy(easyrsa_dir / "pki" / "ca.crt", instance_dir / "ca.crt")
            
            # Generate DH params (or use ECDH)
            # For modern setup, use ecdh-curve instead
            
            # Generate tls-crypt-v2 key
            tls_key_path = instance_dir / "tls-crypt-v2.key"
            subprocess.run(
                ["openvpn", "--genkey", "tls-crypt-v2-server", str(tls_key_path)],
                check=True,
                capture_output=True
            )
            
            expiry = OpenVPNService._parse_cert_expiry(cert_path)
            
            logger.info(f"Server certificate generated for {instance_id}")
            return {
                "success": True,
                "expiry": expiry
            }
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate server cert: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def generate_client_cert(instance_id: str, client_name: str, days: int = 3650) -> Dict:
        """Generate client certificate."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        
        try:
            subprocess.run(
                ["./easyrsa", "--batch", f"--days={days}",
                 "build-client-full", client_name, "nopass"],
                cwd=easyrsa_dir,
                check=True,
                capture_output=True
            )
            
            cert_path = easyrsa_dir / "pki" / "issued" / f"{client_name}.crt"
            key_path = easyrsa_dir / "pki" / "private" / f"{client_name}.key"
            
            expiry = OpenVPNService._parse_cert_expiry(cert_path)
            fingerprint = OpenVPNService._get_cert_fingerprint(cert_path)
            
            logger.info(f"Client certificate generated: {client_name}")
            return {
                "success": True,
                "cert": cert_path.read_text(),
                "key": key_path.read_text(),
                "expiry": expiry,
                "fingerprint": fingerprint
            }
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate client cert: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def revoke_client_cert(instance_id: str, client_name: str) -> bool:
        """Revoke a client certificate and regenerate CRL."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        
        try:
            # Revoke certificate
            subprocess.run(
                ["./easyrsa", "--batch", "revoke", client_name],
                cwd=easyrsa_dir,
                check=True,
                capture_output=True
            )
            
            # Regenerate CRL
            OpenVPNService.regenerate_crl(instance_id)
            
            # Immediately disconnect the client
            OpenVPNService.kill_client(instance_id, client_name)
            
            # Remove cert files
            for ext in [".crt", ".key", ".req"]:
                cert_file = easyrsa_dir / "pki" / "issued" / f"{client_name}{ext}"
                if cert_file.exists():
                    cert_file.unlink()
                key_file = easyrsa_dir / "pki" / "private" / f"{client_name}{ext}"
                if key_file.exists():
                    key_file.unlink()
            
            logger.info(f"Client certificate revoked: {client_name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to revoke cert: {e}")
            return False
    
    # CRL validity window. easy-rsa default is 180 days; the server config uses
    # `crl-verify`, so an expired CRL makes OpenVPN reject every TLS handshake
    # ("CRL has expired") — the daemon stays up but no client can connect. We
    # mint long-lived CRLs and refresh them well before expiry (see
    # renew_crl_if_needed + the background loop in the on_startup hook).
    CRL_VALIDITY_DAYS = 3650
    CRL_RENEW_THRESHOLD_DAYS = 30

    @staticmethod
    def regenerate_crl(instance_id: str) -> bool:
        """Regenerate Certificate Revocation List with a long validity window."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        instance_dir = OpenVPNService.get_instance_dir(instance_id)

        try:
            env = {
                **subprocess.os.environ,
                "EASYRSA_CRL_DAYS": str(OpenVPNService.CRL_VALIDITY_DAYS),
            }
            subprocess.run(
                ["./easyrsa", "gen-crl"],
                cwd=easyrsa_dir,
                env=env,
                check=True,
                capture_output=True
            )

            # Copy CRL to instance directory
            crl_src = easyrsa_dir / "pki" / "crl.pem"
            crl_dst = instance_dir / "crl.pem"
            shutil.copy(crl_src, crl_dst)
            crl_dst.chmod(0o644)

            logger.info(f"CRL regenerated for {instance_id}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to regenerate CRL: {e}")
            return False

    @staticmethod
    def get_crl_days_remaining(instance_id: str) -> Optional[int]:
        """Days until the instance CRL nextUpdate. None if no CRL / parse error."""
        crl_path = OpenVPNService.get_instance_dir(instance_id) / "crl.pem"
        if not crl_path.exists():
            return None
        try:
            result = subprocess.run(
                ["openssl", "crl", "-nextupdate", "-noout", "-in", str(crl_path)],
                capture_output=True,
                text=True,
            )
            # Output: nextUpdate=Jan  7 12:00:00 2036 GMT
            match = re.search(r'nextUpdate=(.+)', result.stdout)
            if not match:
                return None
            next_update = datetime.strptime(match.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
            return (next_update - datetime.utcnow()).days
        except Exception as e:
            logger.error(f"Failed to parse CRL nextUpdate for {instance_id}: {e}")
            return None

    @staticmethod
    def renew_crl_if_needed(instance_id: str, threshold_days: int = None) -> bool:
        """Regenerate the CRL if missing or close to expiry, then reload it.

        Returns True if the CRL was regenerated. OpenVPN reads `crl-verify <file>`
        once at startup, so a running instance is restarted to pick up the new CRL
        (renewal is proactive — long before expiry — so this is a rare event).
        """
        if threshold_days is None:
            threshold_days = OpenVPNService.CRL_RENEW_THRESHOLD_DAYS

        days = OpenVPNService.get_crl_days_remaining(instance_id)
        if days is not None and days > threshold_days:
            return False

        logger.info(
            f"CRL for {instance_id} needs renewal "
            f"(days remaining: {days}, threshold: {threshold_days})"
        )
        if not OpenVPNService.regenerate_crl(instance_id):
            return False

        # Reload the daemon so the fresh CRL takes effect (file-mode crl-verify).
        if OpenVPNService.get_instance_status(instance_id):
            try:
                subprocess.run(
                    ["systemctl", "restart", f"openvpn-server@{instance_id}"],
                    check=True, capture_output=True,
                )
                logger.info(f"Restarted openvpn-server@{instance_id} to load renewed CRL")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to restart instance {instance_id} after CRL renewal: {e}")
        return True

    @staticmethod
    def renew_server_cert(instance_id: str, days: int = 3650) -> Dict:
        """Renew server certificate."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        server_name = f"server_{instance_id}"
        
        try:
            # Revoke old cert
            subprocess.run(
                ["./easyrsa", "--batch", "revoke", server_name],
                cwd=easyrsa_dir,
                capture_output=True
            )
            
            # Remove old files
            for subdir in ["issued", "private", "reqs"]:
                for ext in [".crt", ".key", ".req"]:
                    old_file = easyrsa_dir / "pki" / subdir / f"{server_name}{ext}"
                    if old_file.exists():
                        old_file.unlink()
            
            # Generate new certificate
            return OpenVPNService.generate_server_cert(instance_id, days)
        except Exception as e:
            logger.error(f"Failed to renew server cert: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def renew_client_cert(instance_id: str, client_name: str, days: int = 3650) -> Dict:
        """Renew client certificate (revoke old + generate new)."""
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance_id)
        
        try:
            # Revoke old cert
            subprocess.run(
                ["./easyrsa", "--batch", "revoke", client_name],
                cwd=easyrsa_dir,
                capture_output=True
            )
            
            # Remove old files
            for subdir in ["issued", "private", "reqs"]:
                for ext in [".crt", ".key", ".req"]:
                    old_file = easyrsa_dir / "pki" / subdir / f"{client_name}{ext}"
                    if old_file.exists():
                        old_file.unlink()
            
            # Regenerate CRL
            OpenVPNService.regenerate_crl(instance_id)
            
            # Generate new certificate
            return OpenVPNService.generate_client_cert(instance_id, client_name, days)
        except Exception as e:
            logger.error(f"Failed to renew client cert: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _parse_cert_expiry(cert_path: Path) -> Optional[datetime]:
        """Parse certificate expiry date."""
        try:
            result = subprocess.run(
                ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
                capture_output=True,
                text=True
            )
            # Output: notAfter=Jan  7 12:00:00 2036 GMT
            match = re.search(r'notAfter=(.+)', result.stdout)
            if match:
                date_str = match.group(1).strip()
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        except Exception as e:
            logger.error(f"Failed to parse cert expiry: {e}")
        return None
    
    @staticmethod
    def _get_cert_fingerprint(cert_path: Path) -> Optional[str]:
        """Get SHA256 fingerprint of certificate."""
        try:
            result = subprocess.run(
                ["openssl", "x509", "-fingerprint", "-sha256", "-noout", "-in", str(cert_path)],
                capture_output=True,
                text=True
            )
            match = re.search(r'sha256 Fingerprint=(.+)', result.stdout, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        except Exception as e:
            logger.error(f"Failed to get fingerprint: {e}")
        return None
    
    @staticmethod
    def get_cert_days_remaining(expiry: datetime) -> int:
        """Calculate days remaining until expiry."""
        if not expiry:
            return -1
        delta = expiry - datetime.utcnow()
        return max(0, delta.days)
    
    # =========================================================================
    # CCD (Client-Config-Dir) MANAGEMENT
    # =========================================================================
    
    @staticmethod
    def create_ccd_file(instance_id: str, client_name: str, static_ip: str,
                        remote_lans: list = None) -> bool:
        """Create CCD file for static IP assignment and optional site-to-site iroutes."""
        ccd_dir = OpenVPNService.get_ccd_dir(instance_id)
        ccd_file = ccd_dir / client_name

        try:
            ip_only = static_ip.split('/')[0]
            lines = [f"ifconfig-push {ip_only} 255.255.255.0\n"]

            # iroute tells the OpenVPN daemon to route these subnets through
            # this specific client's tunnel (required for server-side s2s routing).
            for lan in (remote_lans or []):
                try:
                    net = IPv4Network(lan, strict=False)
                    lines.append(f"iroute {net.network_address} {net.netmask}\n")
                except Exception:
                    logger.warning(f"Skipping invalid remote_lan in CCD: {lan}")

            ccd_file.write_text("".join(lines))
            ccd_file.chmod(0o644)

            logger.info(f"CCD file created: {client_name} -> {ip_only}, iroutes: {remote_lans or []}")
            return True
        except Exception as e:
            logger.error(f"Failed to create CCD file: {e}")
            return False
    
    @staticmethod
    def delete_ccd_file(instance_id: str, client_name: str) -> bool:
        """Delete CCD file for a client."""
        ccd_file = OpenVPNService.get_ccd_dir(instance_id) / client_name
        
        try:
            if ccd_file.exists():
                ccd_file.unlink()
                logger.info(f"CCD file deleted: {client_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete CCD file: {e}")
            return False
    
    # =========================================================================
    # CONFIG GENERATION
    # =========================================================================
    
    @staticmethod
    def create_server_config(instance: OvpnInstance, remote_routes: list = None) -> str:
        """Generate server configuration file.

        remote_routes: aggregated list of remote LAN CIDRs from all clients with
        remote_lans set. Each CIDR emits a ``route`` directive so the OS on MADMIN
        routes traffic for that subnet through the tun interface. Pairing with the
        per-client ``iroute`` in the CCD file lets OpenVPN dispatch packets to the
        correct tunnel peer.
        """
        instance_dir = OpenVPNService.get_instance_dir(instance.id)
        
        # Parse subnet
        network = IPv4Network(instance.subnet, strict=False)
        
        config_lines = [
            f"# OpenVPN Server Config - {instance.name}",
            f"# Generated by MADMIN",
            "",
            f"port {instance.port}",
            f"proto {instance.protocol}",
            f"dev {instance.interface}",
            "dev-type tun",
            "",
            f"ca {instance_dir}/ca.crt",
            f"cert {instance_dir}/server.crt",
            f"key {instance_dir}/server.key",
            f"crl-verify {instance_dir}/crl.pem",
            f"tls-crypt-v2 {instance_dir}/tls-crypt-v2.key",
            "dh none",  # Use ECDH instead of DH parameters
            "",
            f"server {network.network_address} {network.netmask}",
            f"topology subnet",
            "",
            f"client-config-dir {instance_dir}/ccd",
            "",
            "keepalive 10 120",
            "",
            f"cipher {instance.cipher}",
            f"auth {instance.auth}",
            f"tls-version-min {instance.tls_version_min}",
            "",
            "user nobody",
            "group nogroup",
            "",
            "persist-key",
            "persist-tun",
            "",
            f"status /var/log/openvpn/status_{instance.id}.log",
            f"log-append /var/log/openvpn/{instance.id}.log",
            "verb 3",
            "",
            "# Management interface",
            f"management {OpenVPNService.get_management_socket(instance.id)} unix",
        ]
        
        # DNS servers
        dns_servers = instance.dns_servers if instance.dns_servers else ["8.8.8.8", "1.1.1.1"]
        for dns in dns_servers:
            config_lines.append(f'push "dhcp-option DNS {dns}"')
        
        # Routing
        if instance.tunnel_mode == "full":
            config_lines.append('push "redirect-gateway def1 bypass-dhcp"')
        else:
            # Split tunnel - push specific routes
            for route in instance.routes:
                network_str = route.get('network', '')
                if network_str:
                    try:
                        net = IPv4Network(network_str, strict=False)
                        config_lines.append(f'push "route {net.network_address} {net.netmask}"')
                    except:
                        pass

        # Site-to-site: push each MADMIN-side LAN to connecting clients.
        # Deduplicate against split-tunnel routes already pushed above.
        if getattr(instance, "site_to_site", False) and getattr(instance, "site_to_site_lans", None):
            already_pushed = {
                str(IPv4Network(r.get('network', r) if isinstance(r, dict) else r, strict=False).network_address)
                for r in (instance.routes or [])
                if (r.get('network', r) if isinstance(r, dict) else r)
            }
            for lan in instance.site_to_site_lans:
                try:
                    net = IPv4Network(lan, strict=False)
                except Exception:
                    continue
                if str(net.network_address) not in already_pushed:
                    config_lines.append(f'push "route {net.network_address} {net.netmask}"')

        # Remote-side client LANs: emit a kernel `route` for each so the OS on
        # MADMIN knows to forward traffic destined for those networks through the
        # tun interface. The OpenVPN daemon then dispatches via the CCD iroute.
        for cidr in (remote_routes or []):
            try:
                net = IPv4Network(cidr, strict=False)
                config_lines.append(f"route {net.network_address} {net.netmask}")
            except Exception:
                pass

        return "\n".join(config_lines)
    
    @staticmethod
    def generate_client_config(instance: OvpnInstance, client: OvpnClient, endpoint: str) -> str:
        """Generate unified client .ovpn configuration."""
        instance_dir = OpenVPNService.get_instance_dir(instance.id)
        easyrsa_dir = OpenVPNService.get_easyrsa_dir(instance.id)
        
        # Read certificates and keys
        ca_cert = (instance_dir / "ca.crt").read_text()
        client_cert_path = easyrsa_dir / "pki" / "issued" / f"{client.name}.crt"
        client_key_path = easyrsa_dir / "pki" / "private" / f"{client.name}.key"
        
        # Extract only the certificate part (between BEGIN and END)
        client_cert_full = client_cert_path.read_text()
        cert_match = re.search(r'(-----BEGIN CERTIFICATE-----.*-----END CERTIFICATE-----)', 
                               client_cert_full, re.DOTALL)
        client_cert = cert_match.group(1) if cert_match else client_cert_full
        
        client_key = client_key_path.read_text()
        
        config_lines = [
            "# OpenVPN Client Config",
            f"# Instance: {instance.name}",
            f"# Client: {client.name}",
            f"# Generated: {datetime.utcnow().isoformat()}",
            "",
            "client",
            "dev tun",
            f"proto {instance.protocol}",
            f"remote {endpoint} {instance.port}",
            "resolv-retry infinite",
            "nobind",
            "",
            "persist-key",
            "persist-tun",
            "",
            "remote-cert-tls server",
            f"cipher {instance.cipher}",
            f"auth {instance.auth}",
            "auth-nocache",
            f"tls-version-min {instance.tls_version_min}",
            "",
            "verb 3",
            "",
        ]
        
        # Add inline certificates
        config_lines.extend([
            "<ca>",
            ca_cert.strip(),
            "</ca>",
            "",
            "<cert>",
            client_cert.strip(),
            "</cert>",
            "",
            "<key>",
            client_key.strip(),
            "</key>",
            "",
        ])
        
        # Add tls-crypt-v2 client key
        tls_server_key = instance_dir / "tls-crypt-v2.key"
        if tls_server_key.exists():
            # Generate per-client tls-crypt-v2 key
            # Use temp file for output to avoid issues with /dev/stdout
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                result = subprocess.run(
                    ["openvpn", "--tls-crypt-v2", str(tls_server_key),
                     "--genkey", "tls-crypt-v2-client", tmp_path],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    # Read generated key
                    with open(tmp_path, 'r') as f:
                        key_content = f.read()
                        
                    config_lines.extend([
                        "<tls-crypt-v2>",
                        key_content.strip(),
                        "</tls-crypt-v2>",
                    ])
                else:
                    raise RuntimeError(f"OpenVPN key gen failed (code {result.returncode}). Stdout: {result.stdout}, Stderr: {result.stderr}")

            except Exception as e:
                logger.error(f"Could not generate tls-crypt-v2 client key. Command output: {e.stderr if hasattr(e, 'stderr') else str(e)}")
                # This is critical for connection, so we shouldn't fail silently
                # If we return partial config, connection will fail with "TLS Error: could not determine wrapping"
                raise RuntimeError(f"Failed to generate tls-crypt-v2 key: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        return "\n".join(config_lines)
    
    # =========================================================================
    # INTERFACE CONTROL
    # =========================================================================
    
    @classmethod
    async def bring_instance_up(cls, instance, db) -> bool:
        """
        Start an instance (server or client) and apply its firewall rules.
        Shared by the /start endpoint and the on_startup restore hook so both
        paths produce an identical firewall state.
        """
        if instance.direction == "client":
            if not cls.start_client_instance(instance.id):
                return False
            cls.apply_instance_firewall_rules(
                instance.id, instance.port, instance.protocol,
                instance.interface, instance.subnet,
                instance.tunnel_mode, instance.routes,
                instance.firewall_default_policy,
                direction="client",
                client_lan_interfaces=instance.client_lan_interfaces,
            )
            return True

        if not cls.start_instance(instance.id):
            return False
        cls.apply_instance_firewall_rules(
            instance.id, instance.port, instance.protocol,
            instance.interface, instance.subnet,
            instance.tunnel_mode, instance.routes,
            instance.firewall_default_policy,
            site_to_site=instance.site_to_site,
            site_to_site_lans=instance.site_to_site_lans,
        )
        await cls.apply_group_firewall_rules(instance.id, db)
        return True

    @classmethod
    async def bring_instance_down(cls, instance, db) -> bool:
        """Stop an instance (server or client) and remove its firewall rules."""
        if instance.direction == "client":
            if not cls.stop_client_instance(instance.id):
                return False
            cls.remove_instance_firewall_rules(
                instance.id, instance.interface,
                client_lan_interfaces=instance.client_lan_interfaces,
            )
            return True

        if not cls.stop_instance(instance.id):
            return False
        await cls.remove_all_group_chains(instance.id, db)
        cls.remove_instance_firewall_rules(instance.id, instance.interface)
        return True

    @staticmethod
    def start_instance(instance_id: str) -> bool:
        """Start OpenVPN instance."""
        try:
            subprocess.run(
                ["systemctl", "start", f"openvpn-server@{instance_id}"],
                check=True,
                capture_output=True
            )
            logger.info(f"Started OpenVPN instance: {instance_id}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start instance: {e}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start instance: {e}")
            return False
            
    @staticmethod
    def get_management_socket(instance_id: str) -> Path:
        """Get management socket path."""
        return Path(f"/var/run/openvpn/mgmt_{instance_id}.sock")
            
    @staticmethod
    def send_management_command(instance_id: str, command: str) -> str:
        """Send command to OpenVPN management interface."""
        import socket
        
        sock_path = OpenVPNService.get_management_socket(instance_id)
        if not sock_path.exists():
            return ""
            
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)  # 5 second timeout
                s.connect(str(sock_path))
                
                # Use file object for easier line reading
                f = s.makefile('r', encoding='utf-8')
                
                # Consume banner (wait for it to stop sending or just read first lines?)
                # Banner usually starts immediately. We can just ignore it or read until we can send.
                # Actually, standard OpenVPN management does not send a prompt by default unless 'state on' etc.
                # We can just send the command. But we might have pending banner data in buffer.
                # It's safer to just send.
                
                s.sendall(f"{command}\n".encode())
                
                response = ""
                while True:
                    line = f.readline()
                    if not line:
                        break
                    
                    response += line
                    
                    # Check for termination conditions
                    if line.strip() == "END":
                        break
                    if line.startswith("SUCCESS:") or line.startswith("ERROR:"):
                        # Single line commands like 'kill' return immediate status
                        break
                
                s.sendall(b"quit\n")
                return response
        except Exception as e:
            logger.error(f"Management command failed: {e}")
            return ""
            
    @staticmethod
    def kill_client(instance_id: str, client_name: str) -> bool:
        """Disconnect a connected client immediately."""
        logger.info(f"Killing client {client_name} on instance {instance_id}")
        response = OpenVPNService.send_management_command(instance_id, f"kill {client_name}")
        return "SUCCESS" in response

    # =========================================================================
    # CLIENT MODE — import, materialize, start/stop, upstream status
    # =========================================================================

    @staticmethod
    def get_client_dir(instance_id: str) -> Path:
        return OPENVPN_CLIENT_DIR / instance_id

    @staticmethod
    def parse_imported_ovpn(text: str) -> dict:
        """Parse a .ovpn client config. Returns dict + warnings list.

        Supports inline certificate blocks (<ca>, <cert>, <key>,
        <tls-crypt>, <tls-crypt-v2>, <tls-auth>).
        """
        result: dict = {
            "remote_host": None,
            "remote_port": 1194,
            "proto": "udp",
            "dev": "tun",
            "auth_user_pass_required": False,
            "ca": None,
            "cert": None,
            "key": None,
            "tls_crypt": None,
            "tls_crypt_v2": None,
            "tls_auth": None,
            "tls_auth_direction": None,
            "warnings": [],
        }

        # Extract inline blocks
        inline_re = re.compile(
            r'<(ca|cert|key|tls-crypt|tls-crypt-v2|tls-auth)>\s*(.*?)\s*</\1>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in inline_re.finditer(text):
            tag = m.group(1).lower().replace("-", "_")
            content = m.group(2).strip()
            result[tag] = content

        stripped = inline_re.sub("", text)

        for line in stripped.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            parts = line.split()
            d = parts[0].lower()

            if d == "remote" and len(parts) >= 2 and result["remote_host"] is None:
                result["remote_host"] = parts[1]
                if len(parts) >= 3:
                    try:
                        result["remote_port"] = int(parts[2])
                    except ValueError:
                        pass
            elif d == "proto" and len(parts) >= 2:
                proto = parts[1].lower()
                # normalise tcp4/tcp6 → tcp, udp4/udp6 → udp
                result["proto"] = proto.rstrip("46")
            elif d == "dev" and len(parts) >= 2:
                result["dev"] = parts[1]
            elif d == "auth-user-pass":
                result["auth_user_pass_required"] = True
            elif d == "key-direction" and len(parts) >= 2:
                result["tls_auth_direction"] = parts[1]
            elif d == "tls-auth" and len(parts) >= 3:
                result["tls_auth_direction"] = parts[2]

        # Warnings
        if not result["remote_host"]:
            result["warnings"].append("'remote' directive not found")
        if not result["ca"]:
            result["warnings"].append("CA certificate missing (inline <ca> block required)")
        if not result["cert"]:
            result["warnings"].append("Client certificate missing (inline <cert> block required)")
        if not result["key"]:
            result["warnings"].append("Client key missing (inline <key> block required)")
        if not (result["tls_crypt"] or result["tls_crypt_v2"] or result["tls_auth"]):
            result["warnings"].append("No TLS auth/crypt key found (connection less secure)")
        if result["auth_user_pass_required"]:
            result["warnings"].append("Server requires username/password authentication")

        return result

    @staticmethod
    def materialize_client_instance(instance, parsed: dict) -> bool:
        """Write all client config files and /etc/openvpn/client/{id}.conf."""
        client_dir = OpenVPNService.get_client_dir(instance.id)
        client_dir.mkdir(parents=True, exist_ok=True)

        if parsed.get("ca"):
            (client_dir / "ca.crt").write_text(parsed["ca"])
        if parsed.get("cert"):
            (client_dir / "client.crt").write_text(parsed["cert"])
        if parsed.get("key"):
            key_path = client_dir / "client.key"
            key_path.write_text(parsed["key"])
            key_path.chmod(0o600)

        tls_directive = None
        if parsed.get("tls_crypt_v2"):
            tls_path = client_dir / "tls.key"
            tls_path.write_text(parsed["tls_crypt_v2"])
            tls_directive = f"tls-crypt-v2 {tls_path}"
        elif parsed.get("tls_crypt"):
            tls_path = client_dir / "tls.key"
            tls_path.write_text(parsed["tls_crypt"])
            tls_directive = f"tls-crypt {tls_path}"
        elif parsed.get("tls_auth"):
            tls_path = client_dir / "tls.key"
            tls_path.write_text(parsed["tls_auth"])
            direction = parsed.get("tls_auth_direction") or "1"
            tls_directive = f"tls-auth {tls_path} {direction}"

        auth_line = None
        if instance.auth_username and instance.auth_password:
            auth_txt = client_dir / "auth.txt"
            auth_txt.write_text(f"{instance.auth_username}\n{instance.auth_password}\n")
            auth_txt.chmod(0o600)
            auth_line = f"auth-user-pass {auth_txt}"

        # Named tun interface: strip 'cli_' prefix, truncate to fit IFNAMSIZ (max 15)
        short = re.sub(r'[^a-zA-Z0-9]', '', instance.id)[:11]
        tun_iface = f"tcli{short}"[:15]

        sock_path = OpenVPNService.get_management_socket(instance.id)

        lines = [
            "client",
            f"dev {tun_iface}",
            "dev-type tun",
            f"proto {parsed.get('proto', 'udp')}",
            f"remote {parsed['remote_host']} {parsed.get('remote_port', 1194)}",
            "resolv-retry infinite",
            "nobind",
            "persist-key",
            "persist-tun",
            "remote-cert-tls server",
            "verb 3",
            f"management {sock_path} unix",
            "",
            f"ca {client_dir}/ca.crt",
        ]
        if parsed.get("cert"):
            lines.append(f"cert {client_dir}/client.crt")
        if parsed.get("key"):
            lines.append(f"key {client_dir}/client.key")
        if tls_directive:
            lines.append(tls_directive)
        if auth_line:
            lines.append(auth_line)

        conf_path = OPENVPN_CLIENT_DIR / f"{instance.id}.conf"
        conf_path.write_text("\n".join(lines) + "\n")
        conf_path.chmod(0o600)

        logger.info(f"Materialized OVPN client instance {instance.id} at {conf_path}")
        return True

    @staticmethod
    def start_client_instance(instance_id: str) -> bool:
        try:
            subprocess.run(
                ["systemctl", "start", f"openvpn-client@{instance_id}"],
                check=True, capture_output=True,
            )
            logger.info(f"Started OVPN client instance: {instance_id}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start client instance {instance_id}: {e.stderr}")
            return False

    @staticmethod
    def stop_client_instance(instance_id: str) -> bool:
        try:
            subprocess.run(
                ["systemctl", "stop", f"openvpn-client@{instance_id}"],
                check=True, capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def get_client_instance_status(instance_id: str) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", f"openvpn-client@{instance_id}"],
                capture_output=True, text=True,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    @staticmethod
    def get_client_upstream_status(instance_id: str) -> dict:
        """Query management socket for VPN client connection state."""
        state_resp = OpenVPNService.send_management_command(instance_id, "state")
        stats_resp = OpenVPNService.send_management_command(instance_id, "load-stats")

        status = {
            "state": "unknown",
            "connected": False,
            "tunnel_ip": None,
            "bytes_in": 0,
            "bytes_out": 0,
        }

        for line in state_resp.splitlines():
            # Format: timestamp,STATE,desc,local_ip,...
            line = line.lstrip(">STATE:").strip()
            if "," in line:
                parts = line.split(",")
                if len(parts) >= 2:
                    state_name = parts[1].upper()
                    status["state"] = state_name
                    status["connected"] = (state_name == "CONNECTED")
                    if len(parts) >= 4 and parts[3]:
                        status["tunnel_ip"] = parts[3]
                break

        m = re.search(r'bytesin=(\d+),bytesout=(\d+)', stats_resp)
        if m:
            status["bytes_in"] = int(m.group(1))
            status["bytes_out"] = int(m.group(2))

        return status

    @staticmethod
    def stop_instance(instance_id: str) -> bool:
        """Stop OpenVPN instance."""
        try:
            subprocess.run(
                ["systemctl", "stop", f"openvpn-server@{instance_id}"],
                check=True,
                capture_output=True
            )
            logger.info(f"Stopped OpenVPN instance: {instance_id}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to stop instance: {e}")
            return False
    
    @staticmethod
    def get_instance_status(instance_id: str) -> bool:
        """Check if instance is running."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", f"openvpn-server@{instance_id}"],
                capture_output=True,
                text=True
            )
            return result.stdout.strip() == "active"
        except:
            return False
    
    @staticmethod
    def get_connected_clients(instance_id: str) -> List[Dict]:
        """Get list of connected clients via status file."""
        # Check standard systemd path first, then config path
        possible_paths = [
            Path(f"/run/openvpn-server/status-{instance_id}.log"),
            Path(f"/var/log/openvpn/status_{instance_id}.log")
        ]
        
        status_file = None
        for p in possible_paths:
            if p.exists():
                status_file = p
                break
        
        connected = []
        if not status_file:
            return connected
        
        try:
            content = status_file.read_text()
            
            # Detect version 2 (starts with TITLE, has HEADER)
            is_v2 = "CLIENT_LIST" in content
            
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                if is_v2:
                    if line.startswith('CLIENT_LIST'):
                        # TIME,HEADER fields show:
                        # CLIENT_LIST,CommonName,RealAddress,VirtualAddress,VirtualIPv6,BytesReceived,BytesSent,ConnectedSince,...
                        parts = line.split(',')
                        if len(parts) >= 8:
                            connected.append({
                                'common_name': parts[1],
                                'real_address': parts[2],
                                'virtual_address': parts[3],
                                'bytes_received': int(parts[5]) if parts[5].isdigit() else 0,
                                'bytes_sent': int(parts[6]) if parts[6].isdigit() else 0,
                                'connected_since': parts[7],
                            })
                else:
                    # Version 1 parsing
                    if line.startswith('ROUTING TABLE'):
                        break
                    # V1 client list section typically starts after "Common Name,..." header
                    # But reliable way involves skipping headers
                    if ',' in line and not line.startswith('Updated') and not line.startswith('Common Name'):
                        parts = line.split(',')
                        if len(parts) >= 5:
                            connected.append({
                                'common_name': parts[0],
                                'real_address': parts[1],
                                # V1 doesn't always show VIP in client list, but in routing table
                                'bytes_received': int(parts[2]) if parts[2].isdigit() else 0,
                                'bytes_sent': int(parts[3]) if parts[3].isdigit() else 0,
                                'connected_since': parts[4],
                            })
                            
        except Exception as e:
            logger.error(f"Failed to parse status file {status_file}: {e}")
        
        return connected
    
    # =========================================================================
    # IP ALLOCATION
    # =========================================================================
    
    @staticmethod
    async def allocate_client_ip(session: AsyncSession, instance: OvpnInstance) -> str:
        """Allocate next available IP for client."""
        network = IPv4Network(instance.subnet, strict=False)
        
        # Get all allocated IPs
        result = await session.execute(
            select(OvpnClient.allocated_ip).where(
                OvpnClient.instance_id == instance.id
            )
        )
        used_ips = {row[0].split('/')[0] for row in result.all()}
        
        # Server uses .1
        used_ips.add(str(network.network_address + 1))
        
        # Find first available
        for i, ip in enumerate(network.hosts()):
            if i == 0:  # Skip .1 (server)
                continue
            if str(ip) not in used_ips:
                return f"{ip}/32"
        
        raise ValueError("No available IPs in subnet")
    
    # =========================================================================
    # FIREWALL MANAGEMENT
    # =========================================================================
    
    @staticmethod
    def _get_default_interface() -> str:
        """Detect the default network interface."""
        return get_default_interface() or "eth0"

    @staticmethod
    def _get_group_chain_name(chain_id: str, group_name: str) -> str:
        """Generate a group chain name that fits within iptables 29-char limit.

        Format: OVPN_GRP_{instance_8chars}_{group_8chars}
        Total: 9 + 8 + 1 + 8 = 26 chars max
        """
        inst_part = chain_id[:8]
        grp_part = group_name[:8]
        return f"OVPN_GRP_{inst_part}_{grp_part}"
    
    @staticmethod
    def initialize_module_firewall_chains() -> bool:
        """Initialize module-level firewall chains."""
        core_iptables.create_or_flush_chain(OpenVPNService.OVPN_INPUT_CHAIN, "filter")
        core_iptables.create_or_flush_chain(OpenVPNService.OVPN_FORWARD_CHAIN, "filter")
        core_iptables.create_or_flush_chain(OpenVPNService.OVPN_NAT_CHAIN, "nat")
        
        # Add RETURN at end of chains
        # Remove any existing RETURN first to avoid duplicates
        core_iptables.run_safe("filter", ["-D", OpenVPNService.OVPN_INPUT_CHAIN, "-j", "RETURN"], suppress_errors=True)
        core_iptables.run_safe("filter", ["-D", OpenVPNService.OVPN_FORWARD_CHAIN, "-j", "RETURN"], suppress_errors=True)
        core_iptables.run_safe("nat", ["-D", OpenVPNService.OVPN_NAT_CHAIN, "-j", "RETURN"], suppress_errors=True)

        core_iptables.run_safe("filter", ["-A", OpenVPNService.OVPN_INPUT_CHAIN, "-j", "RETURN"])
        core_iptables.run_safe("filter", ["-A", OpenVPNService.OVPN_FORWARD_CHAIN, "-j", "RETURN"])
        core_iptables.run_safe("nat", ["-A", OpenVPNService.OVPN_NAT_CHAIN, "-j", "RETURN"])
        
        logger.info("OpenVPN module firewall chains initialized")
        return True
    
    @staticmethod
    def apply_instance_firewall_rules(
        instance_id: str,
        port: Optional[int],
        protocol: str,
        interface: str,
        subnet: Optional[str],
        tunnel_mode: str = "full",
        routes: list = None,
        firewall_default_policy: str = "ACCEPT",
        site_to_site: bool = False,
        site_to_site_lans: list = None,
        direction: str = "server",
        client_lan_interfaces: list = None,
    ) -> bool:
        """Apply firewall rules for an OpenVPN instance.

        direction='client': LAN-gateway rules (MASQUERADE LAN→tun, FORWARD per
        client_lan_interfaces). direction='server' (default): server rules with
        optional site_to_site NAT-exempt mode.
        """
        chain_id = instance_id.replace('tun', '') if instance_id.startswith('tun') else instance_id
        input_chain = f"OVPN_{chain_id}_INPUT"
        forward_chain = f"OVPN_{chain_id}_FWD"
        nat_chain = f"OVPN_{chain_id}_NAT"

        logger.info(
            f"Applying firewall rules for OpenVPN instance {instance_id} "
            f"(direction: {direction}, mode: {tunnel_mode})"
        )

        # Create/flush instance chains (both modes)
        core_iptables.create_or_flush_chain(input_chain, "filter")
        core_iptables.create_or_flush_chain(forward_chain, "filter")
        core_iptables.create_or_flush_chain(nat_chain, "nat")

        # ---- CLIENT MODE ----
        if direction == "client":
            lan_ifaces = [l for l in (client_lan_interfaces or []) if l]

            # INPUT: allow return traffic from the upstream VPN
            core_iptables.run_safe("filter", [
                "-A", input_chain, "-i", interface,
                "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
            ])
            core_iptables.run_safe("filter", ["-A", input_chain, "-j", "RETURN"])

            # FORWARD: LAN → tunnel + established return
            for lan in lan_ifaces:
                core_iptables.run_safe("filter", [
                    "-A", forward_chain, "-i", lan, "-o", interface, "-j", "ACCEPT",
                ])
                core_iptables.run_safe("filter", [
                    "-A", forward_chain, "-i", interface, "-o", lan,
                    "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
                ])
            core_iptables.run_safe("filter", ["-A", forward_chain, "-j", "RETURN"])

            # NAT: MASQUERADE LAN traffic into tunnel
            if tunnel_mode == "split" and routes:
                for route in routes:
                    network = route.get('network') if isinstance(route, dict) else route
                    if network:
                        core_iptables.run_safe("nat", [
                            "-A", nat_chain, "-d", network, "-o", interface, "-j", "MASQUERADE",
                        ])
            else:
                core_iptables.run_safe("nat", [
                    "-A", nat_chain, "-o", interface, "-j", "MASQUERADE",
                ])
            core_iptables.run_safe("nat", ["-A", nat_chain, "-j", "RETURN"])

            # Link to module chains
            core_iptables.ensure_jump_rule(OpenVPNService.OVPN_INPUT_CHAIN, input_chain, "filter")
            for lan in lan_ifaces:
                core_iptables.ensure_interface_jump_rule(
                    OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
                    input_interface=lan,
                )
            core_iptables.ensure_interface_jump_rule(
                OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
                input_interface=interface,
            )
            core_iptables.ensure_jump_rule(OpenVPNService.OVPN_NAT_CHAIN, nat_chain, "nat")
            return True

        # ---- SERVER MODE ----
        wan_interface = OpenVPNService._get_default_interface()
        s2s_lans = [l for l in (site_to_site_lans or []) if l]

        # INPUT rules
        core_iptables.run_safe("filter", [
            "-A", input_chain, "-p", protocol, "--dport", str(port), "-j", "ACCEPT"
        ])
        core_iptables.run_safe("filter", [
            "-A", input_chain, "-i", interface, "-j", "ACCEPT"
        ])
        core_iptables.run_safe("filter", [
            "-A", input_chain, "-j", "RETURN"
        ])

        # FORWARD rules for response traffic - DIRECT accept in module chain
        # This ensures traffic TO the VPN interface is accepted without going through instance chain
        core_iptables.ensure_interface_rule(
            OpenVPNService.OVPN_FORWARD_CHAIN, "ACCEPT", "filter",
            output_interface=interface
        )

        # Site-to-site: bidirectional ACCEPT for each LAN<->VPN subnet pair so the
        # forward chain explicitly permits LAN->VPN traffic regardless of the
        # interface-jump filter (which only matches -i {vpn_iface}).
        if site_to_site and s2s_lans and subnet:
            for lan in s2s_lans:
                core_iptables.run_safe("filter", [
                    "-A", forward_chain, "-s", lan, "-d", subnet,
                    "-m", "comment", "--comment", f"s2s_{instance_id}",
                    "-j", "ACCEPT",
                ])
                core_iptables.run_safe("filter", [
                    "-A", forward_chain, "-s", subnet, "-d", lan,
                    "-m", "comment", "--comment", f"s2s_{instance_id}",
                    "-j", "ACCEPT",
                ])

        # FORWARD: Apply default policy / route enforcement
        if tunnel_mode == "split" and routes and firewall_default_policy == "ACCEPT":
            # Split tunnel + ACCEPT: restrict traffic to defined routes only
            for route in routes:
                network = route.get('network') if isinstance(route, dict) else route
                if network:
                    core_iptables.run_safe("filter", [
                        "-A", forward_chain, "-d", network, "-j", "ACCEPT"
                    ])
            # Drop everything else (route enforcement)
            core_iptables.run_safe("filter", ["-A", forward_chain, "-j", "DROP"])
            logger.info(f"  Split tunnel enforcement: ACCEPT only to defined routes, DROP rest")
        else:
            # Full tunnel OR split+DROP: apply default policy directly
            core_iptables.run_safe("filter", [
                "-A", forward_chain, "-i", interface, "-j", firewall_default_policy
            ])
            logger.info(f"  Traffic from VPN policy: {firewall_default_policy}")

        # NAT rules
        if site_to_site and s2s_lans and subnet:
            # NAT-exempt: terminating ACCEPT for LAN<->VPN pairs. These are specific
            # src/dst matches so internet-bound traffic falls through to MASQUERADE below.
            for lan in s2s_lans:
                core_iptables.run_safe("nat", [
                    "-A", nat_chain, "-s", lan, "-d", subnet,
                    "-m", "comment", "--comment", f"s2s_{instance_id}",
                    "-j", "ACCEPT",
                ])
                core_iptables.run_safe("nat", [
                    "-A", nat_chain, "-s", subnet, "-d", lan,
                    "-m", "comment", "--comment", f"s2s_{instance_id}",
                    "-j", "ACCEPT",
                ])
            logger.info(f"  Site-to-site NAT-exempt for LANs: {s2s_lans} <-> {subnet}")

        # MASQUERADE for non-exempt traffic (internet in full tunnel; split routes; or
        # traffic that didn't match any S2S ACCEPT above).
        if tunnel_mode == "split" and routes:
            for route in routes:
                network = route.get('network') if isinstance(route, dict) else route
                out_iface = route.get('interface') if isinstance(route, dict) and route.get('interface') else wan_interface
                if network:
                    core_iptables.run_safe("nat", [
                        "-A", nat_chain, "-s", subnet, "-d", network, "-o", out_iface, "-j", "MASQUERADE"
                    ])
        else:
            # Full tunnel: masquerade remaining traffic (internet-bound; LAN traffic was
            # already handled by S2S ACCEPT rules above if site_to_site is set).
            core_iptables.run_safe("nat", [
                "-A", nat_chain, "-s", subnet, "-o", wan_interface, "-j", "MASQUERADE"
            ])

        # Ensure only one RETURN at end of NAT chain
        core_iptables.run_safe("nat", ["-D", nat_chain, "-j", "RETURN"], suppress_errors=True)
        core_iptables.run_safe("nat", ["-A", nat_chain, "-j", "RETURN"])
        
        # Link to module chains
        core_iptables.ensure_jump_rule(OpenVPNService.OVPN_INPUT_CHAIN, input_chain, "filter")
        # FORWARD chain: Only need jump for traffic FROM VPN (input interface)
        # Traffic TO VPN is already handled by direct ACCEPT rule above
        core_iptables.ensure_interface_jump_rule(
            OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
            input_interface=interface
        )
        core_iptables.ensure_jump_rule(OpenVPNService.OVPN_NAT_CHAIN, nat_chain, "nat")
        
        return True
    
    @staticmethod
    def apply_client_remote_lan_rules(instance_id: str, client_name: str, remote_lans: list) -> None:
        """Add ACCEPT rules in the instance FORWARD chain for each remote_lan CIDR.

        Needed for split-tunnel: traffic from behind-client networks arrives with a
        source IP outside the VPN subnet, so the generic drop-at-end-of-chain would
        block it. These rules are inserted before the final DROP.
        """
        chain_id = instance_id.replace('ovpn_', '') if instance_id.startswith('ovpn_') else instance_id
        forward_chain = f"OVPN_{chain_id}_FWD"
        for lan in (remote_lans or []):
            # Idempotent: remove first, then re-add
            core_iptables.run_safe("filter", [
                "-D", forward_chain, "-s", lan,
                "-m", "comment", "--comment", f"rl_{client_name}",
                "-j", "ACCEPT",
            ], suppress_errors=True)
            core_iptables.run_safe("filter", [
                "-I", forward_chain, "1",
                "-s", lan,
                "-m", "comment", "--comment", f"rl_{client_name}",
                "-j", "ACCEPT",
            ])
            logger.info(f"  Remote LAN rule: -s {lan} -j ACCEPT (rl_{client_name})")

    @staticmethod
    def remove_client_remote_lan_rules(instance_id: str, client_name: str, remote_lans: list) -> None:
        """Remove per-client remote_lan ACCEPT rules from the instance FORWARD chain."""
        chain_id = instance_id.replace('ovpn_', '') if instance_id.startswith('ovpn_') else instance_id
        forward_chain = f"OVPN_{chain_id}_FWD"
        for lan in (remote_lans or []):
            core_iptables.run_safe("filter", [
                "-D", forward_chain, "-s", lan,
                "-m", "comment", "--comment", f"rl_{client_name}",
                "-j", "ACCEPT",
            ], suppress_errors=True)

    @staticmethod
    def remove_instance_firewall_rules(instance_id: str, interface: str = None,
                                        client_lan_interfaces: list = None) -> bool:
        """Remove firewall rules for an instance."""
        chain_id = instance_id.replace('tun', '') if instance_id.startswith('tun') else instance_id
        input_chain = f"OVPN_{chain_id}_INPUT"
        forward_chain = f"OVPN_{chain_id}_FWD"
        nat_chain = f"OVPN_{chain_id}_NAT"

        # Remove INPUT jump
        core_iptables.run_safe("filter", [
            "-D", OpenVPNService.OVPN_INPUT_CHAIN, "-j", input_chain
        ], suppress_errors=True)

        # Remove FORWARD jumps
        if interface:
            core_iptables.remove_interface_jump_rule(
                OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
                input_interface=interface,
            )
            core_iptables.remove_interface_jump_rule(
                OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
                output_interface=interface,
            )
        # Client-mode LAN interface jumps
        for lan in (client_lan_interfaces or []):
            core_iptables.remove_interface_jump_rule(
                OpenVPNService.OVPN_FORWARD_CHAIN, forward_chain, "filter",
                input_interface=lan,
            )
        # Fallback: non-filtered jump (legacy / server mode)
        core_iptables.run_safe("filter", [
            "-D", OpenVPNService.OVPN_FORWARD_CHAIN, "-j", forward_chain
        ], suppress_errors=True)
        
        # Remove NAT jump
        core_iptables.run_safe("nat", [
            "-D", OpenVPNService.OVPN_NAT_CHAIN, "-j", nat_chain
        ], suppress_errors=True)
        
        # Delete chains
        core_iptables.delete_chain(input_chain, "filter")
        core_iptables.delete_chain(forward_chain, "filter")
        core_iptables.delete_chain(nat_chain, "nat")
        
        logger.info(f"Firewall rules removed for instance {instance_id}")
        return True
    
    @staticmethod
    async def remove_all_group_chains(instance_id: str, db) -> bool:
        """
        Remove all group chains for an instance.
        Should be called before deleting an instance.
        """
        from .models import OvpnGroup
        
        logger.info(f"Removing group chains for instance {instance_id}")
        
        # Get all groups for this instance
        result = await db.execute(select(OvpnGroup).where(OvpnGroup.instance_id == instance_id))
        groups = result.scalars().all()
        
        # chain_id for naming consistency
        chain_id = instance_id.replace('tun', '') if instance_id.startswith('tun') else instance_id
        
        for group in groups:
            # Group chain name with truncation to fit iptables limit
            group_name = group.id.replace(instance_id + '_', '')
            group_chain = OpenVPNService._get_group_chain_name(chain_id, group_name)
            core_iptables.delete_chain(group_chain, "filter")
            logger.info(f"  Deleted chain: {group_chain}")
        
        return True
    
    @staticmethod
    async def apply_group_firewall_rules(instance_id: str, db) -> bool:
        """
        Apply firewall rules for all groups in an instance.
        
        Chain hierarchy:
        OVPN_{instance}_FWD → OVPN_GRP_{group_id} → rules → default policy
        
        For each group member, traffic from their IP is matched and jumped
        to the group's chain where rules are applied.
        """
        from .models import OvpnInstance, OvpnGroup, OvpnGroupMember, OvpnGroupRule, OvpnClient
        
        logger.info(f"Applying group firewall rules for instance {instance_id}")
        
        # Get instance
        result = await db.execute(select(OvpnInstance).where(OvpnInstance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            logger.error(f"Instance {instance_id} not found")
            return False

        # Skip iptables operations if the instance is not running.
        # Chains won't exist until the instance is started; rules will be applied then.
        if not OpenVPNService.get_instance_status(instance_id):
            logger.info(f"Instance {instance_id} is not running, skipping iptables")
            return True

        # Instance forward chain name
        chain_id = instance_id.replace('tun', '') if instance_id.startswith('tun') else instance_id
        instance_fwd_chain = f"OVPN_{chain_id}_FWD"
        
        # Get all groups for this instance, ordered by priority (lower order = higher priority)
        # We process in DESC order because we insert at position 1 (LIFO), so the last processed (lowest order) ends up first.
        result = await db.execute(
            select(OvpnGroup).where(OvpnGroup.instance_id == instance_id).order_by(OvpnGroup.order.desc())
        )
        groups = result.scalars().all()
        
        # 1. Cleanup all existing group jump rules from the instance forward chain
        # Get current rules
        success, output = core_iptables.run_safe_with_output(
            "filter", ["-S", instance_fwd_chain], suppress_errors=True
        )
        if success and output:
            for line in output.splitlines():
                # Line format: -A OVPN_tun0_FWD -s 10.8.0.2/32 -j OVPN_GRP_foo
                if "-j OVPN_GRP_" in line:
                    parts = line.split()
                    # Reconstruct delete command
                    # remove '-A'
                    if parts[0] == '-A':
                        parts[0] = '-D'
                        core_iptables.run_safe("filter", parts)

        for group in groups:
            # Group chain name with truncation to fit iptables limit
            group_name = group.id.replace(instance_id + '_', '')
            group_chain = OpenVPNService._get_group_chain_name(chain_id, group_name)
            
            # Create group chain
            core_iptables.create_or_flush_chain(group_chain, "filter")
            
            # Get rules for this group (ordered)
            result = await db.execute(
                select(OvpnGroupRule)
                .where(OvpnGroupRule.group_id == group.id)
                .order_by(OvpnGroupRule.order)
            )
            rules = result.scalars().all()
            
            # Add rules to group chain
            for rule in rules:
                args = ["-A", group_chain]
                
                # Protocol
                if rule.protocol and rule.protocol != "all":
                    args.extend(["-p", rule.protocol])
                
                # Destination
                if rule.destination and rule.destination != "0.0.0.0/0":
                    args.extend(["-d", rule.destination])
                
                # Port (only for tcp/udp)
                if rule.port and rule.protocol in ("tcp", "udp"):
                    args.extend(["--dport", rule.port])
                
                # Action
                args.extend(["-j", rule.action])
                
                core_iptables.run_safe("filter", args)
            
            # Group chain ends with RETURN - default policy is at instance level
            core_iptables.run_safe("filter", [
                "-A", group_chain, "-j", "RETURN"
            ])
            
            # Get members of this group
            result = await db.execute(
                select(OvpnGroupMember, OvpnClient)
                .join(OvpnClient, OvpnGroupMember.client_id == OvpnClient.id)
                .where(OvpnGroupMember.group_id == group.id)
            )
            members = result.all()
            
            # For each member, add a jump rule from instance chain to group chain
            for member, client in members:
                client_ip = client.allocated_ip.split('/')[0]  # Remove /32
                
                # Add jump rule matching source IP at beginning of instance chain
                # First remove any existing rule for this IP
                core_iptables.run_safe("filter", [
                    "-D", instance_fwd_chain, "-s", client_ip, "-j", group_chain
                ], suppress_errors=True)
                
                # Insert at position 1 (before the default ACCEPT rules)
                core_iptables.run_safe("filter", [
                    "-I", instance_fwd_chain, "1", "-s", client_ip, "-j", group_chain
                ])
                
                logger.info(f"  Added rule: {client_ip} -> {group_chain}")
                
            # Cleanup stale jump rules ( IPs that are no longer in groups or moved groups)
            # This is tricky because we only know current members.
            # Best approach: Get ALL jump rules in the chain, identify those jumping to OVPN_GRP_*,
            # and verify if they match valid members.
            
            # For strict correctness and performance, we can just FLUSH all jump rules from the chain
            # that target ANY OVPN_GRP_* chain, and rebuild them.
            # But we are inside a loop over groups... efficient?
            
            # Alternative: modifying the loop logic.
            # 1. Collect all VALID (ip, group_chain) pairs.
            # 2. Flush existing OVPN_GRP_* jumps from instance chain.
            # 3. Apply all pairs.
            
            # Since this function iterates all groups, we can accumulate rules and apply them at the end?
            # Or assume we just keep adding rules and rely on `remove_member` to clean up?
            # Revocation calls this function but the client is NOT in `members` anymore.
            # So `remove_member` specific logic is skipped.
            
            # Fix: At the start of this function (before group loop), iterate the forward chain
            # and remove ALL jumps to OVPN_GRP_*.
            pass
        
        # After processing all groups, update the instance forward chain policy/enforcement

        # Remove old policy rules (ACCEPT, DROP, RETURN) from the end
        for target in ["ACCEPT", "DROP", "RETURN"]:
            core_iptables.run_safe("filter", [
                "-D", instance_fwd_chain, "-j", target
            ], suppress_errors=True)
            core_iptables.run_safe("filter", [
                "-D", instance_fwd_chain, "-i", instance.interface, "-j", target
            ], suppress_errors=True)
            core_iptables.run_safe("filter", [
                "-D", instance_fwd_chain, "-j", target
            ], suppress_errors=True)

        # Remove route enforcement rules (split tunnel)
        if instance.routes:
            for route in instance.routes:
                network = route.get('network') if isinstance(route, dict) else route
                if network:
                    core_iptables.run_safe("filter", [
                        "-D", instance_fwd_chain, "-d", network, "-j", "ACCEPT"
                    ], suppress_errors=True)

        # Re-add policy/enforcement rules at end
        if instance.tunnel_mode == "split" and instance.routes and instance.firewall_default_policy == "ACCEPT":
            for route in instance.routes:
                network = route.get('network') if isinstance(route, dict) else route
                if network:
                    core_iptables.run_safe("filter", [
                        "-A", instance_fwd_chain, "-d", network, "-j", "ACCEPT"
                    ])
            core_iptables.run_safe("filter", ["-A", instance_fwd_chain, "-j", "DROP"])
        else:
            core_iptables.run_safe("filter", [
                "-A", instance_fwd_chain, "-i", instance.interface, "-j", instance.firewall_default_policy
            ])

        logger.info(f"Group firewall rules applied for instance {instance_id}")
        logger.info(f"  Default policy for non-grouped clients: {instance.firewall_default_policy}")
        return True
    
    @staticmethod
    async def remove_group_firewall_rules(instance_id: str, group_id: str, group_name: str, db) -> bool:
        """Remove firewall rules for a specific group."""
        from .models import OvpnGroupMember, OvpnClient
        
        # Instance forward chain name
        chain_id = instance_id.replace('tun', '') if instance_id.startswith('tun') else instance_id
        instance_fwd_chain = f"OVPN_{chain_id}_FWD"
        # Group chain name with truncation to fit iptables limit
        group_chain = OpenVPNService._get_group_chain_name(chain_id, group_name)
        
        logger.info(f"Removing firewall rules for group {group_name} (chain: {group_chain})")
        
        # Get members to remove their jump rules
        result = await db.execute(
            select(OvpnGroupMember, OvpnClient)
            .join(OvpnClient, OvpnGroupMember.client_id == OvpnClient.id)
            .where(OvpnGroupMember.group_id == group_id)
        )
        members = result.all()
        
        for member, client in members:
            client_ip = client.allocated_ip.split('/')[0] + "/32"
            logger.info(f"  Removing jump rule: {client_ip} -> {group_chain}")
            core_iptables.run_safe("filter", [
                "-D", instance_fwd_chain, "-s", client_ip, "-j", group_chain
            ], suppress_errors=True)
        
        # Delete group chain
        logger.info(f"  Deleting chain: {group_chain}")
        core_iptables.delete_chain(group_chain, "filter")
        
        return True


# Module instance
openvpn_service = OpenVPNService()

