"""
MADMIN Provisioning Subsystem

Auto-provisions a managed LAN (interface + DHCP + NAT) for unattended
virtual-data-center deployments, so VMs deployed behind this router can
always reach the internet by default.

Opt-in via installer flag (--provision-lan). Enforces a "modifiable but
not tamperable" managed configuration through API guards plus a boot-time
self-healing reconciler.
"""
