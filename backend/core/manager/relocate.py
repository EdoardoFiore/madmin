"""
manager.relocate: move this instance to another address of the same manager.

The manager names an https://host:port, never a CA: the new address must
present a certificate under the CA this instance already trusts, and must
serve the agent endpoint. It is checked here first, then saved as
manager_url_next: the agent connects there at once, and only a hello_ack
received from it makes it the manager_url (client.py). If that connection
fails, the next address is dropped and the agent stays where it was, so a
wrong address can never cut the instance off.
"""
import hashlib

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from pydantic import Field

from . import identity as ident, protocol
from .commands import CommandArgs, CommandContext, CommandError, command

_TIMEOUT = 15


class RelocateArgs(CommandArgs):
    url: str = Field(max_length=255)


@command(protocol.CMD_MANAGER_RELOCATE, RelocateArgs, timeout=60)
async def _relocate(args: RelocateArgs, ctx: CommandContext) -> dict:
    from .client import manager_agent
    identity = manager_agent.identity
    if identity is None:
        raise CommandError("istanza non registrata", protocol.ERR_PRECONDITION)
    try:
        url = ident.check_manager_url(args.url)
    except ident.ManagerIdentityError as e:
        raise CommandError(str(e), protocol.ERR_INVALID_ARGS)
    if url == identity.manager_url:
        return {"url": url, "changed": False}
    # Same CA (hostname checked by the context), and it is the agent endpoint
    try:
        async with httpx.AsyncClient(verify=identity.ssl_context(), timeout=_TIMEOUT) as client:
            r = await client.get(f"{url}/agent/ca.pem")
    except httpx.HTTPError as e:
        raise CommandError(f"{url} non raggiungibile con la CA attuale: {type(e).__name__}")
    if r.status_code != 200:
        raise CommandError(f"{url} non è un endpoint agent del manager (HTTP {r.status_code})")
    try:
        served = x509.load_pem_x509_certificates(r.content)
    except ValueError:
        raise CommandError(f"{url} ha restituito una CA non valida")
    fps = {hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).hexdigest() for c in served}
    if not fps & set(ident.trusted_ca_fingerprints()):
        raise CommandError(f"{url} usa una CA diversa da quella di questo manager")
    identity.manager_url_next = url
    ident.save_state(identity)
    return {"url": url, "changed": True}
