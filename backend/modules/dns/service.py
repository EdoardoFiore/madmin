"""
DNS Module - Service Layer

Business logic for DNS operations: config generation, service management,
zone file creation, and DNS query testing.

Uses core utilities:
- core.firewall.iptables for firewall rules (port 53 UDP/TCP)
- core.services.service.SystemdService for bind9 service control
"""
import subprocess
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from sqlalchemy.orm import selectinload

from core.firewall import iptables as core_iptables
from core.services.service import SystemdService

from .models import DnsSettings, DnsZone, DnsRecord, DnsForwarder

logger = logging.getLogger(__name__)

# Paths
BIND_CONF_DIR = Path("/etc/bind")
ZONES_DIR = BIND_CONF_DIR / "zones"
OPTIONS_FILE = BIND_CONF_DIR / "named.conf.options"
LOCAL_FILE = BIND_CONF_DIR / "named.conf.local"

# Templates directory
TEMPLATE_DIR = Path(__file__).parent / "templates"

# Service name
BIND_SERVICE = "named"  # bind9 uses 'named' as service name

# Firewall chain (from manifest)
DNS_FW_CHAIN = "MOD_DNS_INPUT"

# Valid record types
VALID_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS", "PTR"}


class DnsService:
    """Service class for DNS operations."""

    # =========================================================
    #  SETTINGS
    # =========================================================

    async def get_or_create_settings(self, session: AsyncSession) -> DnsSettings:
        """Get global settings (create default row if none exists)."""
        result = await session.execute(select(DnsSettings))
        settings = result.scalar_one_or_none()
        if not settings:
            settings = DnsSettings()
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings

    async def update_settings(self, session: AsyncSession, data: dict) -> DnsSettings:
        """Update global DNS settings."""
        settings = await self.get_or_create_settings(session)
        for key, value in data.items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
        return settings

    # =========================================================
    #  CONFIG GENERATION
    # =========================================================

    def _load_template(self, name: str) -> Template:
        """Load a Jinja2 template from the templates directory."""
        path = TEMPLATE_DIR / name
        return Template(path.read_text())

    def _generate_serial(self) -> str:
        """Generate SOA serial in YYYYMMDDNN format."""
        now = datetime.utcnow()
        return now.strftime("%Y%m%d") + "01"

    def _get_listen_addresses(self, interfaces: List[str]) -> str:
        """Convert interface names to IP addresses for bind9 listen-on."""
        if not interfaces:
            return ""
        
        addresses = ["127.0.0.1"]
        
        try:
            import psutil
            net_if = psutil.net_if_addrs()
            for iface in interfaces:
                if iface in net_if:
                    for addr in net_if[iface]:
                        if addr.family.name == "AF_INET":
                            addresses.append(addr.address)
        except Exception as e:
            logger.warning(f"Could not resolve interface addresses: {e}")
            return ""
        
        return "; ".join(addresses)

    async def generate_options_config(self, session: AsyncSession) -> str:
        """Generate named.conf.options from settings."""
        settings = await self.get_or_create_settings(session)
        
        listen_interfaces = json.loads(settings.listen_interfaces) if settings.listen_interfaces else []
        forwarders = json.loads(settings.system_forwarders) if settings.system_forwarders else []
        
        template = self._load_template("named.conf.options.j2")
        return template.render(
            mode=settings.mode,
            listen_addresses=self._get_listen_addresses(listen_interfaces),
            allow_query=settings.allow_query,
            forwarders=forwarders,
            dnssec_validation=settings.dnssec_validation,
        )

    async def generate_local_config(self, session: AsyncSession) -> str:
        """Generate named.conf.local with zone declarations."""
        # Get enabled zones
        result = await session.execute(
            select(DnsZone).where(DnsZone.enabled == True)
        )
        zones = result.scalars().all()
        
        # Get enabled forwarders
        result = await session.execute(
            select(DnsForwarder).where(DnsForwarder.enabled == True)
        )
        forwarders = result.scalars().all()
        
        # Prepare zone data
        zone_data = []
        for z in zones:
            zd = {
                "name": z.name,
                "zone_type": z.zone_type,
                "forward_servers_list": json.loads(z.forward_servers) if z.forward_servers else [],
            }
            zone_data.append(zd)
        
        # Prepare forwarder data
        fwd_data = []
        for f in forwarders:
            # Skip forwarders whose domain is already a zone
            zone_names = {z.name for z in zones}
            if f.domain not in zone_names:
                fd = {
                    "domain": f.domain,
                    "servers": f.servers,
                    "servers_list": json.loads(f.servers) if f.servers else [],
                }
                fwd_data.append(fd)
        
        template = self._load_template("named.conf.local.j2")
        return template.render(zones=zone_data, forwarders=fwd_data)

    async def generate_zone_file(self, session: AsyncSession, zone: DnsZone) -> str:
        """Generate a zone file for a master zone."""
        # Get records for this zone
        result = await session.execute(
            select(DnsRecord).where(DnsRecord.zone_id == zone.id)
        )
        records = result.scalars().all()
        
        # Prepare record data with TTL string
        rec_data = []
        for r in records:
            rd = {
                "record_type": r.record_type,
                "name": r.name,
                "value": r.value,
                "ttl_str": f"{r.ttl} " if r.ttl else "",
                "priority": r.priority or 10,
                "weight": r.weight or 0,
                "port": r.port or 0,
            }
            rec_data.append(rd)
        
        template = self._load_template("zone.j2")
        return template.render(
            zone_name=zone.name,
            ttl_default=zone.ttl_default,
            serial=self._generate_serial(),
            soa_refresh=zone.soa_refresh,
            soa_retry=zone.soa_retry,
            soa_expire=zone.soa_expire,
            soa_minimum=zone.soa_minimum,
            records=rec_data,
        )

    # =========================================================
    #  WRITE & APPLY
    # =========================================================

    async def write_all_configs(self, session: AsyncSession) -> Tuple[bool, str]:
        """Generate and write all bind9 config files to disk."""
        errors = []
        
        try:
            # Ensure zones directory exists
            ZONES_DIR.mkdir(parents=True, exist_ok=True)
            
            # Write named.conf.options
            options_content = await self.generate_options_config(session)
            OPTIONS_FILE.write_text(options_content)
            logger.info(f"Wrote {OPTIONS_FILE}")
            
            # Write named.conf.local
            local_content = await self.generate_local_config(session)
            LOCAL_FILE.write_text(local_content)
            logger.info(f"Wrote {LOCAL_FILE}")
            
            # Write zone files for master zones
            result = await session.execute(
                select(DnsZone).where(
                    DnsZone.enabled == True,
                    DnsZone.zone_type == "master"
                ).options(selectinload(DnsZone.records))
            )
            zones = result.scalars().all()
            
            for zone in zones:
                zone_file = ZONES_DIR / f"db.{zone.name}"
                zone_content = await self.generate_zone_file(session, zone)
                zone_file.write_text(zone_content)
                logger.info(f"Wrote zone file {zone_file}")
            
            # Clean up zone files for deleted/disabled zones
            existing_zone_names = {f"db.{z.name}" for z in zones}
            for zone_file in ZONES_DIR.glob("db.*"):
                if zone_file.name not in existing_zone_names:
                    zone_file.unlink()
                    logger.info(f"Removed stale zone file {zone_file}")
            
        except PermissionError as e:
            errors.append(f"Permesso negato: {e}")
        except Exception as e:
            errors.append(f"Errore scrittura config: {e}")
        
        if errors:
            return False, "; ".join(errors)
        return True, "Configurazione scritta con successo"

    def validate_config(self) -> Tuple[bool, str]:
        """Validate bind9 config with named-checkconf."""
        try:
            result = subprocess.run(
                ["named-checkconf"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, "Configurazione valida"
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except FileNotFoundError:
            return False, "named-checkconf non trovato. BIND9 è installato?"
        except Exception as e:
            return False, str(e)

    def validate_zone_file(self, zone_name: str) -> Tuple[bool, str]:
        """Validate a zone file with named-checkzone."""
        zone_file = ZONES_DIR / f"db.{zone_name}"
        if not zone_file.exists():
            return False, f"File di zona non trovato: {zone_file}"
        
        try:
            result = subprocess.run(
                ["named-checkzone", zone_name, str(zone_file)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, "Zona valida"
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except FileNotFoundError:
            return False, "named-checkzone non trovato. BIND9 è installato?"
        except Exception as e:
            return False, str(e)

    async def validate_zone_temp(self, session: AsyncSession, zone: DnsZone) -> Tuple[bool, str]:
        """
        Generate a temporary zone file and validate it with named-checkzone.
        
        This does NOT write to any real config files — it uses /tmp for validation.
        Used for pre-commit validation: check if adding/changing a record would
        produce a valid zone before actually committing to the database.
        
        The session should have the pending changes flushed (but not committed).
        """
        import tempfile
        tmp_file = None
        try:
            # Generate zone content from current session state (includes flushed but uncommitted records)
            zone_content = await self.generate_zone_file(session, zone)
            
            # Write to a temp file
            tmp_file = Path(tempfile.mktemp(prefix=f"dns_zone_{zone.name}_", suffix=".zone"))
            tmp_file.write_text(zone_content)
            
            # Validate with named-checkzone
            result = subprocess.run(
                ["named-checkzone", zone.name, str(tmp_file)],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                return True, "Zona valida"
            else:
                # Parse error message to make it user-friendly
                error = result.stderr.strip() or result.stdout.strip()
                # Remove temp file path from errors for cleaner display
                error = error.replace(str(tmp_file), f"db.{zone.name}")
                return False, error
        except FileNotFoundError:
            return False, "named-checkzone non trovato. BIND9 è installato?"
        except Exception as e:
            return False, str(e)
        finally:
            if tmp_file and tmp_file.exists():
                tmp_file.unlink()

    async def apply_config(self, session: AsyncSession) -> Tuple[bool, str]:
        """
        Full apply workflow:
        1. Generate & write configs
        2. Validate config syntax
        3. Apply firewall rules
        4. Restart bind9
        """
        # 1. Write configs
        success, msg = await self.write_all_configs(session)
        if not success:
            return False, f"Errore scrittura: {msg}"
        
        # 2. Validate
        valid, msg = self.validate_config()
        if not valid:
            return False, f"Configurazione non valida: {msg}"
        
        # 3. Apply firewall rules
        self.apply_firewall_rules()
        
        # 4. Restart service
        success, msg = SystemdService.restart(BIND_SERVICE)
        if not success:
            journal_msg = self._get_journal_errors()
            return False, f"Errore riavvio servizio: {msg}. {journal_msg}"
        
        return True, "Configurazione applicata e servizio riavviato"

    async def apply_single_zone(self, session: AsyncSession, zone: DnsZone) -> Tuple[bool, str]:
        """
        Apply config for a single zone:
        1. Write zone file
        2. Update named.conf.local (zone declarations)
        3. Validate zone file with named-checkzone
        4. Reload bind9 gracefully (rndc reload)
        
        This is faster than full apply_config since it doesn't restart the service.
        """
        try:
            ZONES_DIR.mkdir(parents=True, exist_ok=True)
            
            if zone.zone_type == "master":
                # Write zone file
                zone_content = await self.generate_zone_file(session, zone)
                zone_file = ZONES_DIR / f"db.{zone.name}"
                zone_file.write_text(zone_content)
                logger.info(f"Wrote zone file {zone_file}")
                
                # Validate zone file
                valid, msg = self.validate_zone_file(zone.name)
                if not valid:
                    return False, f"Zona non valida: {msg}"
            
            # Update named.conf.local (zone declarations)
            local_content = await self.generate_local_config(session)
            LOCAL_FILE.write_text(local_content)
            
            # Validate full config
            valid, msg = self.validate_config()
            if not valid:
                return False, f"Configurazione non valida: {msg}"
            
            # Reload bind9 gracefully
            ok, msg = self._reload_service()
            if not ok:
                # Fallback to restart
                ok, msg = SystemdService.restart(BIND_SERVICE)
                if not ok:
                    return False, f"Errore reload/restart: {msg}"
            
            return True, "Zona applicata con successo"
            
        except PermissionError as e:
            return False, f"Permesso negato: {e}"
        except Exception as e:
            logger.error(f"Error applying zone {zone.name}: {e}")
            return False, str(e)

    async def remove_zone_files(self, zone_name: str, session: AsyncSession) -> Tuple[bool, str]:
        """
        Remove a zone file and update named.conf.local, then reload.
        """
        try:
            zone_file = ZONES_DIR / f"db.{zone_name}"
            if zone_file.exists():
                zone_file.unlink()
                logger.info(f"Removed zone file {zone_file}")
            
            # Update named.conf.local
            local_content = await self.generate_local_config(session)
            LOCAL_FILE.write_text(local_content)
            
            # Reload
            self._reload_service()
            return True, "Zona rimossa"
        except Exception as e:
            return False, str(e)

    async def apply_settings_only(self, session: AsyncSession) -> Tuple[bool, str]:
        """
        Apply only settings changes (named.conf.options) + reload.
        """
        try:
            options_content = await self.generate_options_config(session)
            OPTIONS_FILE.write_text(options_content)
            
            valid, msg = self.validate_config()
            if not valid:
                return False, f"Configurazione non valida: {msg}"
            
            ok, msg = self._reload_service()
            if not ok:
                ok, msg = SystemdService.restart(BIND_SERVICE)
                if not ok:
                    return False, f"Errore reload: {msg}"
            
            return True, "Impostazioni applicate"
        except Exception as e:
            return False, str(e)

    # =========================================================
    #  SERVICE MANAGEMENT (using core SystemdService)
    # =========================================================

    def get_service_status(self) -> dict:
        """Get bind9 service status using core SystemdService."""
        status = SystemdService.get_status(BIND_SERVICE)
        return {
            "running": status.get("active", False),
            "enabled": status.get("enabled", False),
            "status": status.get("status", "unknown"),
        }

    def start_service(self) -> Tuple[bool, str]:
        """Start bind9 service."""
        return SystemdService.start(BIND_SERVICE)

    def stop_service(self) -> Tuple[bool, str]:
        """Stop bind9 service."""
        return SystemdService.stop(BIND_SERVICE)

    def restart_service(self) -> Tuple[bool, str]:
        """Restart bind9 service."""
        return SystemdService.restart(BIND_SERVICE)

    def _reload_service(self) -> Tuple[bool, str]:
        """Gracefully reload bind9 using rndc reload (no downtime)."""
        try:
            result = subprocess.run(
                ["rndc", "reload"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, "Reload OK"
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except FileNotFoundError:
            # rndc not available, fallback to restart
            return False, "rndc non disponibile"
        except Exception as e:
            return False, str(e)

    def _get_journal_errors(self, lines: int = 20) -> str:
        """Get recent journal entries for bind9."""
        try:
            result = subprocess.run(
                ["journalctl", "-u", BIND_SERVICE, "-n", str(lines), "--no-pager", "-q"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return ""

    # =========================================================
    #  FIREWALL (using core.firewall.iptables)
    # =========================================================

    def apply_firewall_rules(self):
        """
        Apply firewall rules for DNS (port 53 UDP/TCP).
        Uses core.firewall.iptables for rule management.
        """
        try:
            # Create or flush the module chain
            core_iptables.create_or_flush_chain(DNS_FW_CHAIN, "filter")
            
            # Allow DNS on UDP port 53
            core_iptables.add_rule(
                table="filter",
                chain=DNS_FW_CHAIN,
                action="ACCEPT",
                protocol="udp",
                port="53",
                comment="DNS UDP"
            )
            
            # Allow DNS on TCP port 53 (zone transfers, large responses)
            core_iptables.add_rule(
                table="filter",
                chain=DNS_FW_CHAIN,
                action="ACCEPT",
                protocol="tcp",
                port="53",
                comment="DNS TCP"
            )
            
            # Ensure jump rule from INPUT → MOD_DNS_INPUT
            core_iptables.ensure_jump_rule("INPUT", DNS_FW_CHAIN, "filter")
            
            logger.info("DNS firewall rules applied")
        except Exception as e:
            logger.error(f"Failed to apply DNS firewall rules: {e}")

    def remove_firewall_rules(self):
        """Remove DNS firewall rules (called on disable)."""
        try:
            core_iptables.remove_jump_rule("INPUT", DNS_FW_CHAIN, "filter")
            core_iptables.flush_chain(DNS_FW_CHAIN, "filter")
            core_iptables.delete_chain(DNS_FW_CHAIN, "filter")
            logger.info("DNS firewall rules removed")
        except Exception as e:
            logger.warning(f"Error removing DNS firewall rules: {e}")

    # =========================================================
    #  DNS QUERY TEST
    # =========================================================

    def test_query(self, domain: str, record_type: str = "A") -> dict:
        """
        Test a DNS query against the local server using dig.
        
        Returns dict with query result or error.
        """
        try:
            result = subprocess.run(
                ["dig", f"@127.0.0.1", domain, record_type, "+short", "+time=3", "+tries=1"],
                capture_output=True, text=True, timeout=10
            )
            
            output = result.stdout.strip()
            return {
                "success": result.returncode == 0 and bool(output),
                "query": f"{domain} {record_type}",
                "result": output if output else "Nessun risultato",
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except FileNotFoundError:
            return {"success": False, "query": f"{domain} {record_type}",
                    "result": "", "error": "dig non trovato. dnsutils è installato?"}
        except subprocess.TimeoutExpired:
            return {"success": False, "query": f"{domain} {record_type}",
                    "result": "", "error": "Query timeout"}
        except Exception as e:
            return {"success": False, "query": f"{domain} {record_type}",
                    "result": "", "error": str(e)}

    # =========================================================
    #  VALIDATION HELPERS
    # =========================================================

    @staticmethod
    def validate_zone_name(name: str) -> Tuple[bool, str]:
        """Validate a DNS zone name."""
        if not name or len(name) > 253:
            return False, "Nome zona non valido (1-253 caratteri)"
        
        # Must be a valid domain name
        pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$'
        if not re.match(pattern, name):
            return False, "Nome zona contiene caratteri non validi"
        
        return True, ""

    @staticmethod
    def validate_record(record_type: str, name: str, value: str) -> Tuple[bool, str]:
        """Validate a DNS record."""
        if record_type not in VALID_RECORD_TYPES:
            return False, f"Tipo record non valido. Validi: {', '.join(sorted(VALID_RECORD_TYPES))}"
        
        if not name:
            return False, "Il nome del record è obbligatorio"
        
        if not value:
            return False, "Il valore del record è obbligatorio"
        
        # Type-specific validation
        if record_type == "A":
            # Must be valid IPv4
            parts = value.split(".")
            if len(parts) != 4:
                return False, "Indirizzo IPv4 non valido"
            try:
                for p in parts:
                    n = int(p)
                    if n < 0 or n > 255:
                        return False, "Indirizzo IPv4 non valido"
            except ValueError:
                return False, "Indirizzo IPv4 non valido"
        
        elif record_type == "AAAA":
            # Basic IPv6 validation
            if ":" not in value:
                return False, "Indirizzo IPv6 non valido"
        
        return True, ""

    # =========================================================
    #  STATISTICS
    # =========================================================

    async def get_statistics(self, session: AsyncSession) -> dict:
        """Get DNS module statistics."""
        zones_count = (await session.execute(
            select(func.count()).select_from(DnsZone)
        )).scalar() or 0
        
        records_count = (await session.execute(
            select(func.count()).select_from(DnsRecord)
        )).scalar() or 0
        
        forwarders_count = (await session.execute(
            select(func.count()).select_from(DnsForwarder)
        )).scalar() or 0
        
        return {
            "total_zones": zones_count,
            "total_records": records_count,
            "total_forwarders": forwarders_count,
        }

    # =========================================================
    #  INTERFACE DISCOVERY
    # =========================================================

    def get_physical_interfaces(self) -> List[Dict]:
        """
        List physical network interfaces available for DNS listening.
        Excludes: lo, wg*, veth*, docker*, br*, virbr*, tun*, tap*
        """
        exclude_prefixes = ("lo", "wg", "veth", "docker", "br", "virbr", "tun", "tap")
        interfaces = []

        try:
            import psutil
            net_if = psutil.net_if_addrs()
            for iface_name, addrs in net_if.items():
                if any(iface_name.startswith(p) for p in exclude_prefixes):
                    continue

                ipv4 = None
                for addr in addrs:
                    if addr.family.name == "AF_INET":
                        ipv4 = addr.address
                        break

                if ipv4:
                    interfaces.append({
                        "name": iface_name,
                        "ip": ipv4,
                    })
        except Exception as e:
            logger.warning(f"Could not list interfaces: {e}")

        return interfaces


# Singleton instance
dns_service = DnsService()
