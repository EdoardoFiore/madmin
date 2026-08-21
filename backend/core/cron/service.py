"""
MADMIN Crontab Service

Provides crontab management for the system.

Scheduled jobs run as root, so the command is not free text: a job may only
invoke a script that already exists in CRON_SCRIPTS_DIR. MADMIN never writes to
that directory — scripts are placed there by an operator with shell access.
Without that constraint the scheduler would be an arbitrary-command runner with
an HTTP front end.
"""
import os
import re
import shlex
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from config import get_settings

logger = logging.getLogger(__name__)

# Every crontab MADMIN manages belongs to root. Previously the owner was a free
# query parameter, which let any caller read and rewrite any system user's
# crontab.
CRON_USER = "root"

# cron treats '%' as a newline separator: it terminates the command and feeds the
# rest to the job's stdin. shlex.quote does not protect against it, so reject it.
_FORBIDDEN_CHARS = "%\n\r"


class CronService:
    """Service class for crontab operations."""

    # Common preset schedules
    PRESETS = {
        "every_minute": "* * * * *",
        "every_5_minutes": "*/5 * * * *",
        "every_15_minutes": "*/15 * * * *",
        "every_30_minutes": "*/30 * * * *",
        "hourly": "0 * * * *",
        "daily_midnight": "0 0 * * *",
        "daily_6am": "0 6 * * *",
        "daily_noon": "0 12 * * *",
        "weekly_sunday": "0 0 * * 0",
        "weekly_monday": "0 0 * * 1",
        "monthly": "0 0 1 * *",
        "yearly": "0 0 1 1 *",
    }

    # ── Script allowlist ───────────────────────────────────────────────

    @staticmethod
    def scripts_dir() -> Path:
        return Path(get_settings().cron_scripts_dir)

    @staticmethod
    def resolve_script(name: str) -> Path:
        """
        Resolve a script name to a path inside the scripts directory.

        Raises ValueError if the name escapes the directory, does not exist, or
        is not executable.
        """
        base = CronService.scripts_dir().resolve()
        # Path(...).name strips any directory component, so "../../bin/sh"
        # collapses to "sh" and cannot climb out.
        candidate = (base / Path(name).name).resolve()

        if candidate.parent != base:
            raise ValueError("Script path outside the allowed directory")
        if not candidate.is_file():
            raise ValueError(f"Script '{Path(name).name}' not found in {base}")
        if not os.access(candidate, os.X_OK):
            raise ValueError(f"Script '{Path(name).name}' is not executable")

        return candidate

    @staticmethod
    def list_scripts() -> List[Dict]:
        """List executable scripts available to scheduled jobs."""
        base = CronService.scripts_dir()
        if not base.is_dir():
            return []

        scripts = []
        for entry in sorted(base.iterdir()):
            if not entry.is_file() or not os.access(entry, os.X_OK):
                continue
            stat = entry.stat()
            scripts.append({
                "name": entry.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "description": CronService._script_description(entry),
            })
        return scripts

    @staticmethod
    def _script_description(path: Path) -> Optional[str]:
        """First comment line after the shebang, used as a label in the UI."""
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 5:
                        break
                    line = line.strip()
                    if line.startswith("#!") or not line:
                        continue
                    if line.startswith("#"):
                        return line.lstrip("#").strip() or None
                    break
        except OSError:
            pass
        return None

    @staticmethod
    def read_script(name: str) -> str:
        """Read a script's contents for read-only display in the UI."""
        path = CronService.resolve_script(name)
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def build_command(script: str, args: List[str]) -> str:
        """
        Build the command line for a crontab entry.

        The resolved path and every argument are quoted for /bin/sh, which is
        what cron uses to run the job.
        """
        path = CronService.resolve_script(script)

        for arg in args:
            if any(c in arg for c in _FORBIDDEN_CHARS):
                raise ValueError("Arguments cannot contain '%' or line breaks")

        parts = [shlex.quote(str(path))] + [shlex.quote(a) for a in args]
        return " ".join(parts)

    # ── Crontab I/O ────────────────────────────────────────────────────

    @staticmethod
    def _parse_crontab_line(line: str, index: int) -> Optional[Dict]:
        """
        Parse a crontab line into a structured dict.

        Returns None for empty lines only.
        Handles both active entries and disabled (commented) entries.
        """
        line = line.strip()

        # Skip empty lines
        if not line:
            return None

        # Handle comments/disabled entries
        if line.startswith('#'):
            # Check if this is a disabled cron entry (# schedule command)
            content = line[1:].strip()
            parts = content.split(None, 5)
            if len(parts) >= 6:
                # Looks like a disabled cron entry
                schedule = ' '.join(parts[:5])
                command = parts[5]
                return {
                    "id": index,
                    "enabled": False,
                    "raw": line,
                    "comment": None,
                    "schedule": schedule,
                    "command": command,
                    "minute": parts[0],
                    "hour": parts[1],
                    "day": parts[2],
                    "month": parts[3],
                    "weekday": parts[4]
                }
            else:
                # Regular comment
                return {
                    "id": index,
                    "enabled": False,
                    "raw": line,
                    "comment": content,
                    "schedule": None,
                    "command": None
                }

        # Parse active crontab entry
        # Format: minute hour day month weekday command
        parts = line.split(None, 5)
        if len(parts) >= 6:
            schedule = ' '.join(parts[:5])
            command = parts[5]
            return {
                "id": index,
                "enabled": True,
                "raw": line,
                "comment": None,
                "schedule": schedule,
                "command": command,
                "minute": parts[0],
                "hour": parts[1],
                "day": parts[2],
                "month": parts[3],
                "weekday": parts[4]
            }

        # Anything else — an environment assignment, a malformed line — is kept
        # verbatim so a rewrite never drops it.
        return {
            "id": index,
            "enabled": True,
            "raw": line,
            "comment": None,
            "schedule": None,
            "command": line,
            "error": "Malformed crontab line"
        }

    @staticmethod
    def get_crontab() -> Tuple[bool, List[Dict]]:
        """
        Get root's crontab entries.

        Returns:
            Tuple of (success, entries)
        """
        try:
            result = subprocess.run(
                ["crontab", "-u", CRON_USER, "-l"],
                capture_output=True, text=True, timeout=10
            )

            # crontab -l returns 1 if no crontab exists
            if result.returncode != 0:
                if "no crontab" in result.stderr.lower():
                    return True, []
                return False, []

            entries = []
            for line in result.stdout.split('\n'):
                # Index by position in the returned list, not by source line
                # number: blank lines are skipped, and delete/toggle address
                # entries by list position.
                entry = CronService._parse_crontab_line(line, len(entries))
                if entry is not None:
                    entries.append(entry)

            return True, entries

        except subprocess.TimeoutExpired:
            logger.error("Timeout reading crontab")
            return False, []
        except FileNotFoundError:
            logger.error("crontab command not found")
            return False, []
        except Exception as e:
            logger.error(f"Error reading crontab: {e}")
            return False, []

    @staticmethod
    def set_crontab(entries: List[Dict]) -> Tuple[bool, str]:
        """
        Replace root's crontab with the given entries.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Build crontab content
            lines = []
            for entry in entries:
                if entry.get("enabled", True):
                    if entry.get("schedule") and entry.get("command"):
                        lines.append(f"{entry['schedule']} {entry['command']}")
                    elif entry.get("raw"):
                        # Env assignments and lines we could not parse survive untouched
                        lines.append(entry["raw"])
                else:
                    # Disabled entry - add as comment
                    if entry.get("schedule") and entry.get("command"):
                        lines.append(f"# {entry['schedule']} {entry['command']}")
                    elif entry.get("comment"):
                        lines.append(f"# {entry['comment']}")

            crontab_content = '\n'.join(lines) + '\n'

            # Write to crontab via stdin
            result = subprocess.run(
                ["crontab", "-u", CRON_USER, "-"],
                input=crontab_content, capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return False, f"Failed to set crontab: {result.stderr}"

            return True, "Crontab updated successfully"

        except subprocess.TimeoutExpired:
            return False, "Timeout setting crontab"
        except FileNotFoundError:
            return False, "crontab command not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def add_entry(schedule: str, script: str, args: List[str]) -> Tuple[bool, str]:
        """
        Add a new crontab entry running an allowlisted script.

        Raises ValueError if the script is not in the allowed directory.
        """
        command = CronService.build_command(script, args)

        success, entries = CronService.get_crontab()
        if not success:
            return False, "Failed to read current crontab"

        entries.append({
            "id": len(entries),
            "enabled": True,
            "schedule": schedule,
            "command": command
        })

        return CronService.set_crontab(entries)

    @staticmethod
    def update_entry(entry_id: int, schedule: str, script: str, args: List[str]) -> Tuple[bool, str]:
        """
        Replace an existing entry's schedule and command.

        Keeps the entry's position and enabled state: editing a job should not
        silently re-enable one the operator had switched off.

        Raises ValueError if the script is not in the allowed directory.
        """
        command = CronService.build_command(script, args)

        success, entries = CronService.get_crontab()
        if not success:
            return False, "Failed to read current crontab"

        if entry_id < 0 or entry_id >= len(entries):
            return False, "Invalid entry ID"

        entry = entries[entry_id]
        entry["schedule"] = schedule
        entry["command"] = command
        entry.pop("raw", None)  # stale: it still holds the pre-edit line

        return CronService.set_crontab(entries)

    @staticmethod
    def delete_entry(entry_id: int) -> Tuple[bool, str]:
        """Delete a crontab entry by index."""
        success, entries = CronService.get_crontab()
        if not success:
            return False, "Failed to read current crontab"

        if entry_id < 0 or entry_id >= len(entries):
            return False, "Invalid entry ID"

        del entries[entry_id]

        return CronService.set_crontab(entries)

    @staticmethod
    def toggle_entry(entry_id: int) -> Tuple[bool, str]:
        """Toggle enabled/disabled state of a crontab entry."""
        success, entries = CronService.get_crontab()
        if not success:
            return False, "Failed to read current crontab"

        if entry_id < 0 or entry_id >= len(entries):
            return False, "Invalid entry ID"

        entries[entry_id]["enabled"] = not entries[entry_id].get("enabled", True)

        return CronService.set_crontab(entries)

    @staticmethod
    def validate_schedule(schedule: str) -> bool:
        """Validate a cron schedule expression."""
        if any(c in schedule for c in _FORBIDDEN_CHARS):
            return False

        parts = schedule.strip().split()
        if len(parts) != 5:
            return False

        # Each field: *, a number, a list, a range or a step — nothing else, so
        # the schedule cannot smuggle a second command onto the line.
        field = re.compile(r'^(\*|\d+)(-\d+)?(/\d+)?(,(\*|\d+)(-\d+)?(/\d+)?)*$')
        return all(field.match(p) for p in parts)

    @staticmethod
    def describe_schedule(schedule: str) -> str:
        """Generate human-readable description of a schedule."""
        parts = schedule.split()
        if len(parts) != 5:
            return "Invalid schedule"
        
        minute, hour, day, month, weekday = parts
        
        # Match against known presets
        for name, preset in CronService.PRESETS.items():
            if schedule == preset:
                descriptions = {
                    "every_minute": "Ogni minuto",
                    "every_5_minutes": "Ogni 5 minuti",
                    "every_15_minutes": "Ogni 15 minuti",
                    "every_30_minutes": "Ogni 30 minuti",
                    "hourly": "Ogni ora",
                    "daily_midnight": "Ogni giorno a mezzanotte",
                    "daily_6am": "Ogni giorno alle 6:00",
                    "daily_noon": "Ogni giorno a mezzogiorno",
                    "weekly_sunday": "Ogni domenica a mezzanotte",
                    "weekly_monday": "Ogni lunedì a mezzanotte",
                    "monthly": "Ogni mese il 1° giorno",
                    "yearly": "Ogni anno il 1° gennaio"
                }
                return descriptions.get(name, schedule)
        
        # Build simple description
        desc_parts = []
        
        if minute == "*" and hour == "*":
            desc_parts.append("Ogni minuto")
        elif minute == "0" and hour == "*":
            desc_parts.append("Ogni ora")
        elif minute.startswith("*/"):
            desc_parts.append(f"Ogni {minute[2:]} minuti")
        elif hour == "*":
            desc_parts.append(f"Al minuto {minute}")
        else:
            desc_parts.append(f"Alle {hour}:{minute.zfill(2)}")
        
        return " ".join(desc_parts) if desc_parts else schedule


cron_service = CronService()
