#!/usr/bin/env python3
"""
MADMIN Admin Password Reset Script

Emergency CLI tool to reset the admin password when locked out.
Usage: sudo /opt/madmin/venv/bin/python /opt/madmin/backend/scripts/reset-admin-password.py
"""
import asyncio
import sys
import getpass
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from core.database import async_session_factory
from core.auth.models import User
from core.auth.service import get_password_hash


async def reset_admin_password():
    print("=" * 50)
    print("  MADMIN Admin Password Reset")
    print("=" * 50)
    print()
    
    # Get new password
    new_password = getpass.getpass("Nuova password per admin: ")
    if not new_password:
        print("❌ Errore: la password non può essere vuota")
        return False
    
    confirm = getpass.getpass("Conferma password: ")
    
    if new_password != confirm:
        print("❌ Errore: le password non corrispondono")
        return False
    
    if len(new_password) < 6:
        print("❌ Errore: password troppo corta (min 6 caratteri)")
        return False
    
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.username == "admin")
            )
            admin = result.scalar_one_or_none()
            
            if not admin:
                print("❌ Errore: utente admin non trovato nel database")
                return False
            
            admin.hashed_password = get_password_hash(new_password)
            session.add(admin)
            await session.commit()
            
            print()
            print("✅ Password admin aggiornata con successo!")
            print()
            print("Ora puoi accedere con:")
            print("  Username: admin")
            print("  Password: [la password appena inserita]")
            return True
            
    except Exception as e:
        print(f"❌ Errore durante l'aggiornamento: {e}")
        return False


async def reset_admin_2fa():
    """Reset 2FA for admin account."""
    print()
    print("=" * 50)
    print("  MADMIN Admin 2FA Reset")
    print("=" * 50)
    print()
    
    confirm = input("Vuoi disattivare la 2FA per l'account admin? [s/N]: ")
    if confirm.lower() != 's':
        print("Operazione annullata.")
        return False
    
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.username == "admin")
            )
            admin = result.scalar_one_or_none()
            
            if not admin:
                print("❌ Errore: utente admin non trovato nel database")
                return False
            
            if not admin.totp_enabled:
                print("ℹ️  La 2FA non è attiva per l'account admin")
                return True
            
            admin.totp_secret = None
            admin.totp_enabled = False
            admin.backup_codes = None
            session.add(admin)
            await session.commit()
            
            print()
            print("✅ 2FA disattivata per l'account admin")
            return True
            
    except Exception as e:
        print(f"❌ Errore: {e}")
        return False


def main():
    print()
    print("Cosa vuoi fare?")
    print("1. Reset password admin")
    print("2. Disattiva 2FA admin")
    print("3. Entrambi")
    print("0. Esci")
    print()
    
    choice = input("Scelta [1/2/3/0]: ").strip()
    
    if choice == "0":
        print("Uscita.")
        return
    
    if choice == "1":
        asyncio.run(reset_admin_password())
    elif choice == "2":
        asyncio.run(reset_admin_2fa())
    elif choice == "3":
        asyncio.run(reset_admin_password())
        asyncio.run(reset_admin_2fa())
    else:
        print("Scelta non valida")


if __name__ == "__main__":
    main()
