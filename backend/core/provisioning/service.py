"""
MADMIN Provisioning Service

Boot-time reconciler and helpers for the managed LAN (interface + DHCP + NAT).

Single source of truth used by:
- the installer trigger (POST /api/provisioning/managed-lan/enable)
- the lifespan boot reconcile (self-heal)
- the Network page (sync DHCP when the managed interface network changes)

All operations are idempotent: they only act on drift.
"""
import ipaddress
import logging
from typing import Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.network.service import NetworkService, NetplanService
from .models import ManagedLanSettings

logger = logging.getLogger(__name__)

# Interfaces never managed/altered (WAN, externally managed by cloud-init)
WAN_INTERFACES = {"eth0"}

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

    def detect_managed_interface(self) -> Optional[str]:
        """
        Resolve the managed LAN interface name at runtime.

        The name is NOT assumed to be "eth1": it may be ens19, enp1s0, etc.
        Returns the first non-virtual interface whose name is not a WAN
        interface, ordered as NetworkService returns them (up first, then name).
        """
        interfaces = NetworkService.get_interfaces()  # already filters virtual ifaces
        # Stable ordering by interface name so "first after eth0" is deterministic
        names = sorted(i["name"] for i in interfaces if i.get("name"))
        for name in names:
            if name not in WAN_INTERFACES:
                return name
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

    # --- Guards helper ---

    async def is_managed_interface(self, session: AsyncSession, name: str) -> bool:
        """True if `name` is the currently managed LAN interface (and provisioning is enabled)."""
        settings = await self.get_or_create_settings(session)
        return bool(settings.enabled and settings.interface and settings.interface == name)

    # --- Drift checks ---

    def _netplan_matches(self, iface: str, address_cidr: str) -> bool:
        """True if the interface's netplan already matches the desired static config."""
        cfg = NetplanService.get_interface_config(iface)
        if not cfg:
            return False
        if cfg.get("dhcp4"):
            return False
        return address_cidr in (cfg.get("addresses") or [])

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

        # 1. Resolve & persist interface
        if not settings.interface:
            detected = self.detect_managed_interface()
            if not detected:
                logger.warning("Managed LAN: no candidate interface after WAN, cannot provision")
                return
            settings.interface = detected
            session.add(settings)
            await session.flush()
            logger.info(f"Managed LAN: resolved interface '{detected}'")

        iface = settings.interface
        network_cidr, gateway_ip, default_start, default_end = self.derive_network(settings.address_cidr)
        range_start = settings.dhcp_range_start or default_start
        range_end = settings.dhcp_range_end or default_end

        # 2. Ensure DHCP module is active (mounts router this boot)
        await self._ensure_dhcp_module(session)

        # 3. Netplan: static IP on the managed interface (only on drift)
        if not self._netplan_matches(iface, settings.address_cidr):
            ok, msg = NetplanService.set_interface_config(
                interface=iface, dhcp4=False, addresses=[settings.address_cidr]
            )
            if ok:
                applied, apply_msg = NetplanService.apply_netplan()
                logger.info(f"Managed LAN: netplan applied for {iface}: {apply_msg}")
            else:
                logger.error(f"Managed LAN: netplan write failed for {iface}: {msg}")

        # 4. Ensure the managed DHCP subnet matches
        await self._ensure_managed_subnet(
            session, iface, network_cidr, gateway_ip, range_start, range_end, settings.dns_servers
        )

        # 5. Ensure the MASQUERADE rule for this interface
        await self._ensure_masquerade(session, iface)

        # 6. Persist desired DHCP runtime state UP (started by on_startup hook)
        await self._set_dhcp_enabled(session, True)

        await session.flush()
        logger.info(f"Managed LAN: reconcile complete (iface={iface}, net={network_cidr})")

    # --- DHCP sync on interface network change ---

    async def sync_dhcp_to_interface(self, session: AsyncSession, address_cidr: str) -> None:
        """
        Called when the user changes the managed interface network (Network page).
        Recompute the managed subnet and re-apply DHCP config.
        """
        settings = await self.get_or_create_settings(session)
        if not (settings.enabled and settings.interface):
            return

        network_cidr, gateway_ip, default_start, default_end = self.derive_network(address_cidr)
        settings.address_cidr = address_cidr
        # Reset stored pool so it is re-derived for the new network
        settings.dhcp_range_start = default_start
        settings.dhcp_range_end = default_end
        session.add(settings)

        await self._ensure_managed_subnet(
            session, settings.interface, network_cidr, gateway_ip,
            default_start, default_end, settings.dns_servers
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
        """Ensure a MASQUERADE rule iface->eth0 exists and is enabled (sentinel-tagged)."""
        from core.firewall.models import MachineFirewallRule

        result = await session.execute(
            select(MachineFirewallRule).where(
                MachineFirewallRule.comment == MANAGED_NAT_SENTINEL
            )
        )
        rule = result.scalar_one_or_none()

        wan = next(iter(WAN_INTERFACES))
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


# Singleton instance
provisioning_service = ProvisioningService()
