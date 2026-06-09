"""
MADMIN Provisioning Service

Boot-time reconciler and helpers for the managed LAN (interface + DHCP + NAT).

Single source of truth used by:
- the installer trigger (POST /api/provisioning/managed-lan/enable)
- the lifespan boot reconcile (self-heal)
- the Network page (resync DHCP from the live interface IP)

The interface IP is assigned externally (by the WAN-managing software); MADMIN
never sets it. All operations are idempotent: they only act on drift.
"""
import ipaddress
import logging
from typing import Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.network.service import NetworkService
from .models import ManagedLanSettings

logger = logging.getLogger(__name__)

# Interfaces never managed/altered (WAN, externally managed by cloud-init).
# eth0 is the legacy WAN name; the real WAN is resolved at runtime via the
# default route (get_default_interface) and excluded too.
WAN_INTERFACES = {"eth0"}

# Known managed-LAN interface names (the second NIC), in preference order.
# The managed LAN is identified STRICTLY by these names — never by IP/position —
# so a spare NIC (e.g. ens2s1) is never auto-selected and detection works even
# before the external software has assigned an IP. If none of these is present,
# provisioning is skipped entirely. Extend per hardware naming convention.
MANAGED_LAN_CANDIDATES = ("eth1", "ens19")

# Sentinel comment marking the managed MASQUERADE rule (for API guards + reconcile)
MANAGED_NAT_SENTINEL = "MADMIN_MANAGED_LAN_NAT"

# Default DHCP pool offsets within the managed network
_RANGE_START_HOST = 100
_RANGE_END_HOST = 200


class ProvisioningService:
    """Managed LAN provisioning logic."""

    # --- Settings access ---

    async def get_or_create_settings(self, session: AsyncSession) -> ManagedLanSettings:
        """Fetch the singleton, creating it (disabled) on first access."""
        result = await session.execute(
            select(ManagedLanSettings).where(ManagedLanSettings.id == 1)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = ManagedLanSettings(id=1)
            session.add(settings)
            await session.flush()
        return settings

    # --- Interface detection ---

    @staticmethod
    def interface_cidr(iface: dict) -> Optional[str]:
        """
        Build the live "ip/prefix" CIDR of an interface dict from
        NetworkService.get_interfaces() (psutil ipv4 + netmask). None if the
        interface has no usable IPv4 address.
        """
        ip = iface.get("ipv4")
        netmask = iface.get("netmask")
        if not ip or not netmask:
            return None
        try:
            net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
            return f"{ip}/{net.prefixlen}"
        except ValueError:
            return None

    def get_live_interface_cidr(self, iface_name: str) -> Optional[str]:
        """Live host CIDR of a NIC by name (e.g. "172.25.1.1/24"), or None."""
        for iface in NetworkService.get_interfaces():
            if iface.get("name") == iface_name:
                return self.interface_cidr(iface)
        return None

    def detect_managed_interface(self) -> Optional[str]:
        """
        Resolve the managed LAN interface name at runtime.

        Rule: the managed LAN is identified STRICTLY by name from
        MANAGED_LAN_CANDIDATES (e.g. "eth1"/"ens19"), matching the first present
        candidate in preference order. This is deterministic and IP-independent:
        a spare NIC (e.g. ens2s1) is never selected, and identification works even
        before the external software has assigned an IP (so the interface can be
        locked immediately). Returns None if no known candidate is present, in
        which case the caller skips provisioning entirely.
        """
        names = {i["name"] for i in NetworkService.get_interfaces() if i.get("name")}
        for candidate in MANAGED_LAN_CANDIDATES:
            if candidate in names:
                return candidate
        return None

    # --- Network derivation ---

    @staticmethod
    def derive_network(address_cidr: str) -> Tuple[str, str, str, str]:
        """
        From a host CIDR (e.g. "172.25.1.1/24") derive:
        (network_cidr, gateway_ip, range_start, range_end).

        Gateway == the interface host IP. Pool defaults to .10–.250 within
        the network (clamped to valid host range).
        """
        iface = ipaddress.IPv4Interface(address_cidr)
        network = iface.network
        gateway_ip = str(iface.ip)
        hosts = list(network.hosts())
        if not hosts:
            raise ValueError(f"Network {network} has no usable host addresses")

        net_base = int(network.network_address)
        start_candidate = ipaddress.IPv4Address(net_base + _RANGE_START_HOST)
        end_candidate = ipaddress.IPv4Address(net_base + _RANGE_END_HOST)

        first_host, last_host = hosts[0], hosts[-1]
        range_start = start_candidate if start_candidate in network and start_candidate >= first_host else first_host
        range_end = end_candidate if end_candidate in network and end_candidate <= last_host else last_host

        # Ensure gateway is not inside the pool when possible
        gw = iface.ip
        if range_start <= gw <= range_end and range_start < last_host:
            # bump start past the gateway if the gateway sits at the low end
            if gw == range_start:
                range_start = ipaddress.IPv4Address(int(gw) + 1)

        return str(network), gateway_ip, str(range_start), str(range_end)

    @staticmethod
    def _pool_within(network_cidr: str, stored_start: Optional[str], stored_end: Optional[str],
                     default_start: str, default_end: str) -> Tuple[str, str]:
        """
        Keep the user-tuned DHCP pool only if it still falls inside the (possibly
        changed) network; otherwise fall back to the derived defaults. Guards
        against a stale pool after the external IP moves to a different subnet.
        """
        try:
            net = ipaddress.IPv4Network(network_cidr)
        except ValueError:
            return default_start, default_end

        def _in(ip: Optional[str]) -> bool:
            if not ip:
                return False
            try:
                return ipaddress.IPv4Address(ip) in net
            except ValueError:
                return False

        start = stored_start if _in(stored_start) else default_start
        end = stored_end if _in(stored_end) else default_end
        return start, end

    # --- Reconcile (self-heal) ---

    async def reconcile(self, session: AsyncSession) -> None:
        """
        Idempotent self-heal of the managed LAN. No-op if not enabled.

        Order matters: must run BEFORE module_loader.load_all_modules() so the
        DHCP module router gets mounted in the same boot. The DHCP service is
        actually started by the DHCP on_startup hook (service_enabled=True).
        """
        settings = await self.get_or_create_settings(session)
        if not settings.enabled:
            logger.info("Managed LAN: provisioning disabled, skipping reconcile")
            return

        # 1. Resolve & persist interface BY NAME (deterministic, IP-independent).
        #    Re-detect every boot so a previously mis-detected/stale name
        #    self-heals to the current known candidate (eth1/ens19).
        detected = self.detect_managed_interface()
        if not detected:
            logger.warning(
                "Managed LAN: no known LAN interface present "
                f"({', '.join(MANAGED_LAN_CANDIDATES)}); skipping provisioning"
            )
            return
        if settings.interface != detected:
            logger.info(f"Managed LAN: interface '{settings.interface}' -> '{detected}'")
            settings.interface = detected
            session.add(settings)
            await session.flush()
        iface = detected

        # 2. Ensure DHCP module is active (mounts router this boot) and the
        #    MASQUERADE rule exists. These are name-only and run even before the
        #    interface has an IP, so the interface is locked/NAT-ready immediately.
        await self._ensure_dhcp_module(session)
        await self._ensure_masquerade(session, iface)

        # 3. Read the LIVE host IP/CIDR (assigned by the WAN-managing software).
        #    We never set the IP ourselves; the DHCP subnet/gateway are derived
        #    from whatever the interface currently holds. Without an IP yet, defer
        #    the DHCP setup (the interface stays identified, locked and NAT-ready).
        live_cidr = self.get_live_interface_cidr(iface)
        if not live_cidr:
            logger.warning(
                f"Managed LAN: interface '{iface}' has no live IPv4 yet; "
                f"deferring DHCP (next boot reconcile will retry)"
            )
            return

        network_cidr, gateway_ip, default_start, default_end = self.derive_network(live_cidr)
        range_start, range_end = self._pool_within(
            network_cidr, settings.dhcp_range_start, settings.dhcp_range_end,
            default_start, default_end,
        )
        # Persist the observed CIDR for display (informational, not a setpoint).
        settings.address_cidr = live_cidr
        session.add(settings)
        await session.flush()

        # 4. Ensure the managed DHCP subnet matches the live interface network
        await self._ensure_managed_subnet(
            session, iface, network_cidr, gateway_ip, range_start, range_end, settings.dns_servers
        )

        # 5. Persist desired DHCP runtime state UP
        await self._set_dhcp_enabled(session, True)

        # 6. Start the DHCP service deterministically. We do NOT rely solely on
        #    the module on_startup hook: it runs later in a background task and its
        #    pre-flight (subnet must match the LIVE interface IP) can lose a race at
        #    early boot before the external software has assigned the IP. The
        #    on_startup hook still runs afterwards as a safety net / retry.
        await session.flush()
        await self._start_dhcp_with_retry(session)

        logger.info(f"Managed LAN: reconcile complete (iface={iface}, net={network_cidr})")

    # --- DHCP resync from the live interface IP ---

    async def resync_managed_dhcp(self, session: AsyncSession) -> None:
        """
        Recompute the managed DHCP subnet from the interface's CURRENT live IP
        (set externally) and re-apply the DHCP config. Called after a DHCP-level
        tweak (DNS/pool) and reusable whenever the bound IP may have changed.
        """
        settings = await self.get_or_create_settings(session)
        if not (settings.enabled and settings.interface):
            return

        live_cidr = self.get_live_interface_cidr(settings.interface)
        if not live_cidr:
            logger.warning(
                f"Managed LAN: cannot resync DHCP, interface "
                f"'{settings.interface}' has no live IPv4"
            )
            return

        network_cidr, gateway_ip, default_start, default_end = self.derive_network(live_cidr)
        range_start, range_end = self._pool_within(
            network_cidr, settings.dhcp_range_start, settings.dhcp_range_end,
            default_start, default_end,
        )
        settings.address_cidr = live_cidr
        session.add(settings)

        await self._ensure_managed_subnet(
            session, settings.interface, network_cidr, gateway_ip,
            range_start, range_end, settings.dns_servers
        )
        await session.flush()
        await self._apply_dhcp(session)

    # --- Internal helpers (lazy-import the optional DHCP module) ---

    async def _ensure_dhcp_module(self, session: AsyncSession) -> None:
        """Activate the DHCP module if not already enabled."""
        from core.modules.models import InstalledModule
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == "dhcp")
        )
        db_module = result.scalar_one_or_none()
        if db_module and db_module.enabled:
            return
        from core.modules.loader import module_loader
        res = await module_loader.activate_module(session, "dhcp")
        if res.get("success"):
            logger.info("Managed LAN: DHCP module activated")
        else:
            logger.error(f"Managed LAN: DHCP module activation failed: {res.get('error')}")

    async def _ensure_managed_subnet(
        self, session: AsyncSession, iface: str, network_cidr: str,
        gateway_ip: str, range_start: str, range_end: str, dns_servers: str
    ) -> None:
        """Create or update the single managed DhcpSubnet."""
        try:
            from modules.dhcp.models import DhcpSubnet
        except Exception as e:
            logger.error(f"Managed LAN: DHCP models unavailable: {e}")
            return

        result = await session.execute(
            select(DhcpSubnet).where(DhcpSubnet.managed == True)  # noqa: E712
        )
        subnet = result.scalar_one_or_none()

        if subnet is None:
            subnet = DhcpSubnet(
                name="Managed LAN",
                network=network_cidr,
                range_start=range_start,
                range_end=range_end,
                gateway=gateway_ip,
                dns_servers=dns_servers,
                interface=iface,
                enabled=True,
                managed=True,
            )
            session.add(subnet)
            logger.info(f"Managed LAN: created managed subnet {network_cidr} on {iface}")
        else:
            subnet.network = network_cidr
            subnet.gateway = gateway_ip
            subnet.interface = iface
            subnet.range_start = range_start
            subnet.range_end = range_end
            subnet.enabled = True
            session.add(subnet)
        await session.flush()

    async def _ensure_masquerade(self, session: AsyncSession, iface: str) -> None:
        """Ensure a MASQUERADE rule iface->WAN exists and is enabled (sentinel-tagged)."""
        from core.firewall.models import MachineFirewallRule
        from core.network.utils import get_default_interface

        result = await session.execute(
            select(MachineFirewallRule).where(
                MachineFirewallRule.comment == MANAGED_NAT_SENTINEL
            )
        )
        rule = result.scalar_one_or_none()

        # Real WAN = default-route interface (e.g. ens18), falling back to the
        # legacy eth0 name. Re-resolved each reconcile so the NAT egress self-heals.
        wan = get_default_interface() or next(iter(WAN_INTERFACES))
        if rule is None:
            max_order = (await session.execute(
                select(func.max(MachineFirewallRule.order)).where(
                    MachineFirewallRule.table_name == "nat"
                )
            )).scalar() or 0
            rule = MachineFirewallRule(
                chain="POSTROUTING",
                action="MASQUERADE",
                in_interface=iface,
                out_interface=wan,
                table_name="nat",
                comment=MANAGED_NAT_SENTINEL,
                order=max_order + 1,
                enabled=True,
            )
            session.add(rule)
            logger.info(f"Managed LAN: created MASQUERADE {iface}->{wan}")
        else:
            rule.in_interface = iface
            rule.out_interface = wan
            rule.enabled = True
            session.add(rule)
        await session.flush()

    async def _set_dhcp_enabled(self, session: AsyncSession, enabled: bool) -> None:
        """Persist DHCP desired runtime state."""
        try:
            from modules.dhcp.service import dhcp_service
        except Exception as e:
            logger.error(f"Managed LAN: DHCP service unavailable: {e}")
            return
        dhcp_settings = await dhcp_service.get_or_create_settings(session)
        dhcp_settings.service_enabled = enabled
        session.add(dhcp_settings)
        await session.flush()

    async def _apply_dhcp(self, session: AsyncSession) -> None:
        """Re-generate and apply DHCP config (restarts the service)."""
        try:
            from modules.dhcp.service import dhcp_service
        except Exception as e:
            logger.error(f"Managed LAN: DHCP service unavailable: {e}")
            return
        ok, msg = await dhcp_service.apply_config(session)
        if ok:
            logger.info("Managed LAN: DHCP config re-applied")
        else:
            logger.error(f"Managed LAN: DHCP apply failed: {msg}")

    async def _start_dhcp_with_retry(self, session: AsyncSession, attempts: int = 3, delay: float = 2.0) -> None:
        """
        Apply DHCP config (which starts/restarts the service), retrying a few
        times to absorb the brief window where the freshly-applied interface IP
        is not yet visible to the config pre-flight at early boot.
        """
        import asyncio
        try:
            from modules.dhcp.service import dhcp_service
        except Exception as e:
            logger.error(f"Managed LAN: DHCP service unavailable: {e}")
            return

        for attempt in range(1, attempts + 1):
            ok, msg = await dhcp_service.apply_config(session)
            if ok:
                logger.info(f"Managed LAN: DHCP service started (attempt {attempt})")
                return
            logger.warning(f"Managed LAN: DHCP start attempt {attempt}/{attempts} failed: {msg}")
            if attempt < attempts:
                await asyncio.sleep(delay)
        logger.error(
            "Managed LAN: DHCP service did not start after retries; "
            "the module on_startup hook will retry"
        )


# Singleton instance
provisioning_service = ProvisioningService()
