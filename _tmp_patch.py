import io

p = 'backend/core/backup/service.py'
s = io.open(p, encoding='utf-8').read()

# ── 1. users import moves after module activation ──────────────────────
old = '''        # 1. Users — includes password hashes and the superuser flag
        users_file = os.path.join(core_path, "users.json")
        if os.path.exists(users_file):
            count = await _import_users(session, users_file)
            result["users_imported"] = count
            logger.info(f"Imported {count} users")
'''
new = '''        # Users are imported last, after the modules: their permission slugs only
        # exist once the module that declares them has been activated, and
        # _import_users silently drops any slug it cannot find. Nothing between
        # here and there references a user row.
        users_file = os.path.join(core_path, "users.json")
'''
assert old in s, 'users block anchor'
s = s.replace(old, new, 1)

old = '''        result["success"] = len(result["errors"]) == 0

        # Schedule auto-restart after successful import
        if result["success"]:
            _schedule_restart()'''
new = '''        # Users last — see the note where users_file is resolved
        if os.path.exists(users_file):
            count = await _import_users(session, users_file)
            result["users_imported"] = count
            logger.info(f"Imported {count} users")
            await session.commit()

        result["success"] = len(result["errors"]) == 0

        # Schedule auto-restart after successful import
        if result["success"]:
            _schedule_restart()'''
assert old in s, 'success anchor'
s = s.replace(old, new, 1)

# ── 2. carry the password policy through export/import ─────────────────
old = '''            "totp_locked": user.totp_locked,
            "backup_codes": user.backup_codes,
            "preferences": user.preferences,
            "permissions": permission_slugs'''
new = '''            "totp_locked": user.totp_locked,
            "backup_codes": user.backup_codes,
            "must_change_password": user.must_change_password,
            "password_expires_at": user.password_expires_at.isoformat() if user.password_expires_at else None,
            "preferences": user.preferences,
            "permissions": permission_slugs'''
assert old in s, 'export dict anchor'
s = s.replace(old, new, 1)

old = '''            existing.backup_codes = backup_codes or existing.backup_codes
            existing.preferences = u_data.get("preferences", existing.preferences)'''
new = '''            existing.backup_codes = backup_codes or existing.backup_codes
            existing.must_change_password = u_data.get(
                "must_change_password", existing.must_change_password)
            existing.password_expires_at = _parse_dt(
                u_data.get("password_expires_at")) or existing.password_expires_at
            existing.preferences = u_data.get("preferences", existing.preferences)'''
assert old in s, 'import existing anchor'
s = s.replace(old, new, 1)

old = '''                totp_locked=totp_locked,
                backup_codes=backup_codes,
                preferences=u_data.get("preferences", "{}")
            )'''
new = '''                totp_locked=totp_locked,
                backup_codes=backup_codes,
                must_change_password=u_data.get("must_change_password", False),
                password_expires_at=_parse_dt(u_data.get("password_expires_at")),
                preferences=u_data.get("preferences", "{}")
            )'''
assert old in s, 'import new anchor'
s = s.replace(old, new, 1)

# helper for the ISO timestamps the export now writes
old = '''async def _import_users(session: AsyncSession, users_file: str) -> int:'''
new = '''def _parse_dt(value):
    """Read back an ISO timestamp written by the export (None-safe)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


async def _import_users(session: AsyncSession, users_file: str) -> int:'''
assert old in s, '_import_users anchor'
s = s.replace(old, new, 1)

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched', p)
