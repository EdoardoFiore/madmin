"""
MADMIN Manager agent (core, not a module).

Connects this instance to a central MADMIN Manager: inventory, backups, support
access (UI and SSH through tunnels opened from here), module licenses.
It has no menu, page or setting: enrollment is done by setup-madmin.sh or
`python -m core.manager enroll`, and every manager action is in the audit log as
manager:<operator>. Without an enrollment it does nothing.

    identity.py   certificate identity, DATA_DIR/manager/
    enroll.py     enrollment (CA pinned by the token), renewal, unenroll
    client.py     control WebSocket (mTLS), reconnects, command dispatch
    protocol.py   wire format, shared with madmin-manager (keep identical)
    commands.py   command registry + audit
    inventory.py  facts and stats sent to the manager
    backups.py    backup.run / backup.restore (to/from the manager only)
    support.py    temporary support accounts, one-time tickets, SSH grants
    sshd.py       OpenSSH CA + principals for support SSH
    tunnel.py     per-connection tunnels to the local UI / SSH
    licenses.py   Ed25519-signed module licenses
"""
