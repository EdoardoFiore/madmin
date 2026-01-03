"""
MADMIN Crontab Service

Provides crontab management for the system.
"""
import subprocess
import logging
import re
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


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
        
        # Malformed line
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
    def get_crontab(user: str = "root") -> Tuple[bool, List[Dict]]:
        """
        Get crontab entries for a user.
        
        Args:
            user: System user whose crontab to retrieve
            
        Returns:
            Tuple of (success, entries)
        """
        try:
            result = subprocess.run(
                ["crontab", "-u", user, "-l"],
                capture_output=True, text=True, timeout=10
            )
            
            # crontab -l returns 1 if no crontab exists
            if result.returncode != 0:
                if "no crontab" in result.stderr.lower():
                    return True, []
                return False, []
            
            lines = result.stdout.split('\n')
            entries = []
            for i, line in enumerate(lines):
                entry = CronService._parse_crontab_line(line, i)
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
    def set_crontab(entries: List[Dict], user: str = "root") -> Tuple[bool, str]:
        """
        Set crontab entries for a user.
        
        Args:
            entries: List of crontab entries
            user: System user whose crontab to set
            
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
                ["crontab", "-u", user, "-"],
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
    def add_entry(schedule: str, command: str, user: str = "root") -> Tuple[bool, str]:
        """Add a new crontab entry."""
        success, entries = CronService.get_crontab(user)
        if not success:
            return False, "Failed to read current crontab"
        
        new_entry = {
            "id": len(entries),
            "enabled": True,
            "schedule": schedule,
            "command": command
        }
        entries.append(new_entry)
        
        return CronService.set_crontab(entries, user)
    
    @staticmethod
    def delete_entry(entry_id: int, user: str = "root") -> Tuple[bool, str]:
        """Delete a crontab entry by index."""
        success, entries = CronService.get_crontab(user)
        if not success:
            return False, "Failed to read current crontab"
        
        if entry_id < 0 or entry_id >= len(entries):
            return False, "Invalid entry ID"
        
        del entries[entry_id]
        
        return CronService.set_crontab(entries, user)
    
    @staticmethod
    def toggle_entry(entry_id: int, user: str = "root") -> Tuple[bool, str]:
        """Toggle enabled/disabled state of a crontab entry."""
        success, entries = CronService.get_crontab(user)
        if not success:
            return False, "Failed to read current crontab"
        
        if entry_id < 0 or entry_id >= len(entries):
            return False, "Invalid entry ID"
        
        entries[entry_id]["enabled"] = not entries[entry_id].get("enabled", True)
        
        return CronService.set_crontab(entries, user)
    
    @staticmethod
    def validate_schedule(schedule: str) -> bool:
        """Validate a cron schedule expression."""
        pattern = r'^(\*|[0-5]?\d)(/\d+)?(\s+(\*|[01]?\d|2[0-3])(/\d+)?){1}(\s+(\*|[1-9]|[12]\d|3[01])(/\d+)?){1}(\s+(\*|[1-9]|1[0-2])(/\d+)?){1}(\s+(\*|[0-7])(/\d+)?){1}$'
        # Simplified check - just verify 5 space-separated fields
        parts = schedule.strip().split()
        return len(parts) == 5
    
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
