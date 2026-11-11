"""
Manager agent CLI (root only, run from the backend directory with the venv):

    python -m core.manager enroll --token-file FILE [--force]   (or MADMIN_MANAGER_TOKEN)
    python -m core.manager register --url https://manager:8443 [--ca-sha256 FP] [--force]
                                (or MADMIN_MANAGER_URL / MADMIN_MANAGER_CA_SHA256)
    python -m core.manager status
    python -m core.manager unenroll [--no-notify]

The running service notices an enroll/unenroll within 30 s: no restart.
"""
import argparse
import asyncio
import json
import logging
import os
import sys


def _token(args) -> str:
    if args.token_file:
        with open(args.token_file) as f:
            return f.read().strip()
    if args.token:
        return args.token.strip()
    token = os.environ.get("MADMIN_MANAGER_TOKEN", "").strip()
    if not token:
        sys.exit("Token mancante: --token-file FILE, --token o MADMIN_MANAGER_TOKEN")
    return token


async def _enroll(args) -> int:
    from .enroll import enroll
    from .identity import ManagerIdentityError
    try:
        identity = await enroll(_token(args), force=args.force)
    except ManagerIdentityError as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERRORE: manager non raggiungibile o risposta non valida ({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    print(f"Registrata sul manager {identity.manager_url} come {identity.instance_id}")
    return 0


async def _register(args) -> int:
    from .enroll import register
    from .identity import ManagerIdentityError
    url = args.url or os.environ.get("MADMIN_MANAGER_URL", "")
    fp = args.ca_sha256 or os.environ.get("MADMIN_MANAGER_CA_SHA256") or None
    if not url:
        sys.exit("URL manager mancante: --url o MADMIN_MANAGER_URL")
    try:
        p = await register(url, fp, force=args.force)
    except ManagerIdentityError as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERRORE: manager non raggiungibile o risposta non valida ({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    print(f"Richiesta di registrazione inviata a {p['manager_url']} (in attesa di approvazione)")
    print(f"  Richiesta:          {p['request_id']}")
    print(f"  Fingerprint chiave: {p['key_fingerprint']}")
    print(f"  Fingerprint CA manager: {p['ca_fingerprint']}")
    if not p["ca_pinned"]:
        print("  ATTENZIONE: CA del manager accettata al primo contatto (nessun --ca-sha256):")
        print("  confrontare il fingerprint CA con quello mostrato dal manager prima di approvare.")
    print("Il servizio MADMIN si collega da solo appena la richiesta viene approvata.")
    return 0


async def _status(args) -> int:
    from . import identity as ident
    try:
        identity = ident.load_identity()
    except ident.ManagerIdentityError as e:
        print(f"Identità non leggibile: {e}")
        return 1
    if identity is None:
        pending = ident.load_pending()
        if pending:
            print(f"Registrazione verso {pending.get('manager_url')}: {pending.get('status')}")
            print(f"Richiesta:          {pending.get('request_id')} ({pending.get('requested_at')})")
            print(f"Fingerprint chiave: {pending.get('key_fingerprint')}")
            print(f"Fingerprint CA manager: {pending.get('ca_fingerprint')}"
                  f"{'' if pending.get('ca_pinned') else ' (non verificato)'}")
            return 0
        print("Non registrata su un manager")
        return 1
    _, not_after = identity.cert_validity()
    print(f"Manager:      {identity.manager_url}")
    print(f"Instance ID:  {identity.instance_id}")
    print(f"Registrata:   {identity.enrolled_at}")
    print(f"Certificato:  valido fino a {not_after.isoformat()}")
    print(f"Revocata:     {'sì' if identity.revoked else 'no'}")
    raw = ident.read_file("status.json")
    if raw:
        s = json.loads(raw)
        print(f"Connessione:  {'connessa' if s.get('connected') else 'non connessa'} (agg. {s.get('at')})")
        if s.get("error"):
            print(f"Ultimo errore: {s['error']}")
    return 0


async def _unenroll(args) -> int:
    from .enroll import unenroll
    await unenroll(notify=not args.no_notify)
    print("Registrazione rimossa")
    return 0


def main() -> None:
    if os.geteuid() != 0:
        sys.exit("Da eseguire come root")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m core.manager")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("enroll")
    p.add_argument("--token-file")
    p.add_argument("--token", help="sconsigliato: resta visibile in ps e nella history")
    p.add_argument("--force", action="store_true", help="sostituisce una registrazione esistente")
    p = sub.add_parser("register")
    p.add_argument("--url", help="https://host:porta del manager (endpoint agent)")
    p.add_argument("--ca-sha256", help="fingerprint sha256 della CA del manager (consigliato)")
    p.add_argument("--force", action="store_true", help="sostituisce una registrazione esistente")
    sub.add_parser("status")
    p = sub.add_parser("unenroll")
    p.add_argument("--no-notify", action="store_true", help="non avvisare il manager")
    args = parser.parse_args()

    handler = {"enroll": _enroll, "register": _register, "status": _status,
               "unenroll": _unenroll}[args.cmd]

    async def run() -> int:
        try:
            return await handler(args)
        finally:
            from core.database import engine
            await engine.dispose()

    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
