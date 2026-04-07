"""
MADMIN Settings Service

Service layer for managing system settings, including Nginx network configuration.
"""
import os
import re
import shutil
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

from config import get_settings
from .models import CertificateInfo, NetworkSettingsResponse

logger = logging.getLogger(__name__)
settings = get_settings()

NGINX_CONF_PATH = "/etc/nginx/sites-available/madmin.conf"
NGINX_PUBLIC_CONF_PATH = "/etc/nginx/sites-available/madmin-public.conf"
NGINX_PUBLIC_CONF_ENABLED = "/etc/nginx/sites-enabled/madmin-public.conf"

# Porte staticamente riservate (non usabili come porta admin o download pubblico)
# 443 è escluso deliberatamente: è un'alternativa valida per il download pubblico
RESERVED_PORTS = {22, 53, 80, 500, 4500, 5432, 8000}

SSL_DIR = Path(settings.data_dir) / "ssl"

# Ensure SSL directory exists
os.makedirs(SSL_DIR, exist_ok=True)


class NetworkService:
    """Service for managing network configuration (Nginx & SSL)."""

    async def get_network_settings(self) -> NetworkSettingsResponse:
        """Get current network configuration."""
        port = await self._get_current_port()
        ssl_enabled = await self._is_ssl_enabled()
        cert_info = await self._get_certificate_info()
        
        return NetworkSettingsResponse(
            management_port=port,
            ssl_enabled=ssl_enabled,
            certificate=cert_info
        )

    async def update_port(self, new_port: int, extra_reserved_ports: set = None) -> bool:
        """
        Update management port in Nginx config.
        Returns True if successful and Nginx reloaded.
        """
        if not 1 <= new_port <= 65535:
            raise ValueError("Invalid port (1-65535)")

        all_reserved = RESERVED_PORTS | (extra_reserved_ports or set())
        if new_port in all_reserved:
            raise ValueError(f"Port {new_port} is already in use by another service")
            
        try:
            # Read config
            content = await self._read_nginx_conf()
            
            # Regex to find listen directive
            # Matches: listen 80; or listen 443 ssl;
            pattern = r"listen\s+(\d+)(?:\s+ssl)?;"
            
            match = re.search(pattern, content)
            if not match:
                raise ValueError("Directive 'listen' not found in Nginx config")
                
            current_port = int(match.group(1))
            full_match = match.group(0)
            
            if current_port == new_port:
                return True
                
            # Replace port
            new_directive = full_match.replace(str(current_port), str(new_port))
            new_content = content.replace(full_match, new_directive)
            
            # Write config
            await self._write_nginx_conf(new_content)
            
            # Reload Nginx
            return await self._reload_nginx()
            
        except Exception as e:
            logger.error(f"Error updating port: {e}")
            raise

    def get_public_download_port(self, url: str) -> int:
        """
        Estrae la porta da un URL. Se non esplicita, restituisce 443 per https.
        """
        parsed = urlparse(url)
        if parsed.port:
            return parsed.port
        return 443 if parsed.scheme == 'https' else 80

    async def update_public_download_block(
        self,
        url: Optional[str],
        extra_reserved_ports: set = None
    ) -> None:
        """
        Crea, aggiorna o rimuove il blocco nginx per il download pubblico dei moduli.
        extra_reserved_ports: porte aggiuntive in uso (istanze VPN, etc.) passate dal router.
        """
        if settings.mock_iptables:
            logger.debug(f"[MOCK] public download nginx block: {url}")
            return

        # --- Disabilita/rimuovi ---
        if not url or not url.strip():
            removed = False
            if os.path.islink(NGINX_PUBLIC_CONF_ENABLED):
                os.remove(NGINX_PUBLIC_CONF_ENABLED)
                removed = True
            if os.path.exists(NGINX_PUBLIC_CONF_PATH):
                os.remove(NGINX_PUBLIC_CONF_PATH)
                removed = True
            if removed:
                await self._reload_nginx()
            return

        # --- Valida porta ---
        port = self.get_public_download_port(url)

        if not (1 <= port <= 65535):
            raise ValueError("Invalid port (1-65535)")

        all_reserved = RESERVED_PORTS | (extra_reserved_ports or set())
        if port in all_reserved:
            raise ValueError(f"Port {port} is already in use by another service")

        admin_port = await self._get_current_port()
        if port == admin_port:
            raise ValueError(f"Port {port} is already used by the administration panel")

        # --- Genera blocco nginx ---
        ssl_crt = str(SSL_DIR / "server.crt")
        ssl_key = str(SSL_DIR / "server.key")

        nginx_block = f"""server {{
    listen {port} ssl;
    server_name _;

    ssl_certificate {ssl_crt};
    ssl_certificate_key {ssl_key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {{ return 403; }}

    # Download configurazioni moduli (magic token, qualsiasi modulo)
    location ~* ^/api/modules/[^/]+/download {{
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

        with open(NGINX_PUBLIC_CONF_PATH, "w") as f:
            f.write(nginx_block)

        # Symlink in sites-enabled (sovrascrive se esiste)
        if os.path.islink(NGINX_PUBLIC_CONF_ENABLED):
            os.remove(NGINX_PUBLIC_CONF_ENABLED)
        os.symlink(NGINX_PUBLIC_CONF_PATH, NGINX_PUBLIC_CONF_ENABLED)

        # Test e reload — rollback su errore
        if not await self._reload_nginx():
            if os.path.islink(NGINX_PUBLIC_CONF_ENABLED):
                os.remove(NGINX_PUBLIC_CONF_ENABLED)
            if os.path.exists(NGINX_PUBLIC_CONF_PATH):
                os.remove(NGINX_PUBLIC_CONF_PATH)
            raise RuntimeError("Invalid Nginx configuration. Check the port and try again.")

    async def renew_self_signed_cert(self) -> CertificateInfo:
        """
        Regenerate self-signed certificate.
        """
        try:
            key_path = SSL_DIR / "server.key"
            crt_path = SSL_DIR / "server.crt"
            
            # Backup existing
            if key_path.exists():
                shutil.copy(key_path, str(key_path) + ".bak")
            if crt_path.exists():
                shutil.copy(crt_path, str(crt_path) + ".bak")
            
            # Generate new cert (10 years)
            cmd = [
                "openssl", "req", "-x509", "-nodes", "-days", "3650",
                "-newkey", "rsa:2048",
                "-keyout", str(key_path),
                "-out", str(crt_path),
                "-subj", "/C=IT/ST=Italy/L=Rome/O=MADMIN/OU=IT/CN=madmin.local"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                raise RuntimeError(f"OpenSSL failed: {stderr.decode()}")
                
            # Set permissions
            os.chmod(key_path, 0o600)
            
            # Reload Nginx to apply
            await self._reload_nginx()
            
            return await self._get_certificate_info()
            
        except Exception as e:
            logger.error(f"Error renewing cert: {e}")
            raise

    async def upload_custom_cert(self, crt_content: bytes, key_content: bytes, ca_content: Optional[bytes] = None) -> CertificateInfo:
        """
        Upload custom certificate and key.
        Optionally append CA chain to the certificate file.
        Verifies the certificate matches the private key before applying.
        """
        try:
            key_path = SSL_DIR / "server.key"
            crt_path = SSL_DIR / "server.crt"
            
            # Temp paths for validation
            temp_key_path = SSL_DIR / "server.key.tmp"
            temp_crt_path = SSL_DIR / "server.crt.tmp"
            
            # Write temp files
            with open(temp_crt_path, "wb") as f:
                f.write(crt_content)
                # Append CA chain if provided
                if ca_content:
                    f.write(b"\n")
                    f.write(ca_content)
            
            with open(temp_key_path, "wb") as f:
                f.write(key_content)
                
            # Set permissions on temp key
            os.chmod(temp_key_path, 0o600)
            
            # Verify certificate matches key
            if not await self._verify_certificate_match(temp_crt_path, temp_key_path):
                # Cleanup temp files
                if temp_crt_path.exists(): os.remove(temp_crt_path)
                if temp_key_path.exists(): os.remove(temp_key_path)
                raise ValueError("The certificate does not match the provided private key.")
            
            # Backup existing
            if key_path.exists():
                shutil.copy(key_path, str(key_path) + ".bak")
            if crt_path.exists():
                shutil.copy(crt_path, str(crt_path) + ".bak")
            
            # Move temp to production
            shutil.move(str(temp_crt_path), str(crt_path))
            shutil.move(str(temp_key_path), str(key_path))
            
            # Reload Nginx
            if not await self._reload_nginx():
                # Rollback if Nginx fails
                if os.path.exists(str(key_path) + ".bak"):
                    shutil.move(str(key_path) + ".bak", key_path)
                if os.path.exists(str(crt_path) + ".bak"):
                    shutil.move(str(crt_path) + ".bak", crt_path)
                await self._reload_nginx()
                raise RuntimeError("Configurazione Nginx non valida con il nuovo certificato")
                
            return await self._get_certificate_info()
            
        except Exception as e:
            logger.error(f"Error uploading cert: {e}")
            # Ensure cleanup
            if (SSL_DIR / "server.crt.tmp").exists(): os.remove(SSL_DIR / "server.crt.tmp")
            if (SSL_DIR / "server.key.tmp").exists(): os.remove(SSL_DIR / "server.key.tmp")
            raise

    # --- Private Helpers ---

    async def _verify_certificate_match(self, crt_path: Path, key_path: Path) -> bool:
        """Verify that certificate public key matches private key modulus."""
        try:
            # Get modulus of certificate
            proc_crt = await asyncio.create_subprocess_exec(
                'openssl', 'x509', '-noout', '-modulus', '-in', str(crt_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_crt_raw, _ = await proc_crt.communicate()

            proc_crt_md5 = await asyncio.create_subprocess_exec(
                'openssl', 'md5',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_crt, _ = await proc_crt_md5.communicate(input=stdout_crt_raw)

            # Get modulus of private key
            proc_key = await asyncio.create_subprocess_exec(
                'openssl', 'rsa', '-noout', '-modulus', '-in', str(key_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_key_raw, _ = await proc_key.communicate()

            proc_key_md5 = await asyncio.create_subprocess_exec(
                'openssl', 'md5',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_key, _ = await proc_key_md5.communicate(input=stdout_key_raw)

            if proc_crt.returncode != 0 or proc_key.returncode != 0:
                logger.error("OpenSSL verification failed")
                return False

            match = stdout_crt.strip() == stdout_key.strip()
            if not match:
                logger.warning("Certificate/key modulus mismatch")
            return match

        except Exception as e:
            logger.error(f"Error verifying cert match: {e}")
            return False

    async def _read_nginx_conf(self) -> str:
        if not os.path.exists(NGINX_CONF_PATH):
            return ""
        with open(NGINX_CONF_PATH, "r") as f:
            return f.read()

    async def _write_nginx_conf(self, content: str):
        with open(NGINX_CONF_PATH, "w") as f:
            f.write(content)

    async def _get_current_port(self) -> int:
        content = await self._read_nginx_conf()
        match = re.search(r"listen\s+(\d+)", content)
        return int(match.group(1)) if match else 80

    async def _is_ssl_enabled(self) -> bool:
        content = await self._read_nginx_conf()
        return "ssl" in content and "listen" in content

    async def _reload_nginx(self) -> bool:
        """Test config and reload Nginx."""
        # Test config
        proc = await asyncio.create_subprocess_shell(
            "nginx -t",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if proc.returncode != 0:
            return False
            
        # Reload
        proc = await asyncio.create_subprocess_shell(
            "systemctl reload nginx",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return proc.returncode == 0

    async def _get_certificate_info(self) -> Optional[CertificateInfo]:
        """Parse certificate info using openssl."""
        crt_path = SSL_DIR / "server.crt"
        if not crt_path.exists():
            return None
            
        try:
            cmd = ["openssl", "x509", "-in", str(crt_path), "-noout", "-dates", "-issuer", "-subject"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            
            if proc.returncode != 0:
                return None
                
            output = stdout.decode()
            info = {}
            for line in output.splitlines():
                if "=" in line:
                    key, val = line.split("=", 1)
                    info[key.strip()] = val.strip()
            
            # Parse dates
            fmt = "%b %d %H:%M:%S %Y %Z"
            valid_from = datetime.strptime(info.get("notBefore", ""), fmt)
            valid_to = datetime.strptime(info.get("notAfter", ""), fmt)
            now = datetime.utcnow()
            days_remaining = (valid_to - now).days
            
            # Check if self-signed (issuer == subject roughly)
            # OpenSSL output format varies, usually subject=... issuer=...
            # For self-signed, they are identical
            is_self_signed = info.get("issuer") == info.get("subject")
            
            return CertificateInfo(
                issuer=info.get("issuer", "Unknown"),
                subject=info.get("subject", "Unknown"),
                valid_from=valid_from,
                valid_to=valid_to,
                days_remaining=days_remaining,
                is_self_signed=is_self_signed
            )
            
        except Exception as e:
            logger.error(f"Error parsing cert info: {e}")
            return None


network_service = NetworkService()
