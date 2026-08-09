#!/usr/bin/env python3
"""
Sync Timing.app and ScreenTime data to Notion database
Enhanced version with entry-level details and macOS ScreenTime integration

Sync Modes:
- PROJECT_TOTALS: Aggregate by project (original behavior)
- ENTRY_LEVEL: Individual time entries with details
- SCREENTIME: macOS ScreenTime app usage data
"""

import requests
from datetime import datetime
import os
import sys
import sqlite3
from dotenv import load_dotenv
import traceback
import json
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Any

# Load environment variables from .env file
load_dotenv()

# Configuration
TIMING_API_TOKEN = os.environ.get("TIMING_API_TOKEN")
NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# Multi-database routing: map a Timing project root/folder to a Notion
# database ID. Project folder -> database ID; any project not matched falls
# back to NOTION_DATABASE_ID. Example:
#   PROJECT_DB_MAP='{"Family": "<family_db_id>", "Work": "<work_db_id>"}'
try:
    PROJECT_DB_MAP = json.loads(os.environ.get("PROJECT_DB_MAP", "{}") or "{}")
except (ValueError, TypeError):
    print("Invalid PROJECT_DB_MAP JSON; ignoring multi-database routing")
    PROJECT_DB_MAP = {}

# Multi-workspace routing: route project folders to different Notion
# workspaces. WORKSPACES defines the registry (name -> auth + per-workspace
# databases); WORKSPACE_MAP maps a project root/folder to a workspace name.
#
#   WORKSPACES='{
#     "gsd":  {"token_env": "NOTION_API_TOKEN",      "databases": {"Family": "family_db_id"}},
#     "flex": {"token_env": "NOTION_API_TOKEN_FLEX", "databases": {"Work": "work_db_id", "Consulting": "consult_db_id"}}
#   }'
#   WORKSPACE_MAP='{"Family": "gsd", "Work": "flex", "Consulting": "flex"}'
#
# Each workspace's API token is read from the named env var (which run-sync.sh
# populates from Keychain/1Password). A project folder that isn't in
# WORKSPACE_MAP falls back to the default workspace: NOTION_API_TOKEN +
# NOTION_DATABASE_ID / PROJECT_DB_MAP. Routing is structural: a folder's
# workspace is fixed by config, so family projects can never land in a work
# workspace and vice versa.
def _parse_json_env(name: str, default: Any):
    try:
        return json.loads(os.environ.get(name, "{}") or "{}")
    except (ValueError, TypeError):
        print(f"Invalid {name} JSON; ignoring")
        return default


WORKSPACES = _parse_json_env("WORKSPACES", {})
WORKSPACE_MAP = _parse_json_env("WORKSPACE_MAP", {})

# Enhanced sync configuration
SYNC_ENTRIES = os.environ.get("SYNC_ENTRIES", "false").lower() == "true"
SYNC_SCREENTIME = os.environ.get("SYNC_SCREENTIME", "false").lower() == "true"
SCREENTIME_TOP_APPS = int(os.environ.get("SCREENTIME_TOP_APPS", "5"))

# Propagate Timing entry custom_fields (device-scoped enrichment markers) into
# the Notion page content for each entry. Only effective when SYNC_ENTRIES=true
# (custom_fields render in the entry-level page content, not the visible
# Project/Duration/Date columns). Absent fields are simply not shown. Read-only:
# the sync never writes custom_fields back to Timing.
SYNC_CUSTOM_FIELDS = os.environ.get("SYNC_CUSTOM_FIELDS", "false").lower() == "true"

# ScreenTime source: "timing" (Timing's own SQLite AppActivity table, FDA-free,
# works under launchd) or "knowledgec" (Apple's knowledgeC.db, requires Full
# Disk Access). Defaults to "timing" because knowledgeC.db is FDA-blocked for
# launchd/cron processes.
SCREENTIME_SOURCE = os.environ.get("SCREENTIME_SOURCE", "timing").lower()

# ScreenTime database locations
SCREENTIME_DB = Path.home() / "Library/Application Support/Knowledge/knowledgeC.db"
TIMING_SQLITE_DB = Path.home() / "Library/Application Support/info.eurocomp.Timing2/SQLite.db"

# Idle handling: when SYNC_WHEN_IDLE is true, the sync runs even if the system
# has been idle for more than the idle threshold. Defaults to false (skip when
# idle), matching the existing behaviour.
SYNC_WHEN_IDLE = os.environ.get("SYNC_WHEN_IDLE", "false").lower() == "true"
IDLE_THRESHOLD_SECONDS = int(os.environ.get("IDLE_THRESHOLD_SECONDS", "300"))

# Error logging configuration
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
ERROR_LOG_FILE = LOG_DIR / "error.log"
MAX_ERROR_ENTRIES = 50


def create_error_file(error_details):
    """Create error file on Desktop with timestamp"""
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    error_file = Path.home() / "Desktop" / f"TIMING_SYNC_ERROR_{timestamp}.txt"

    try:
        with open(error_file, "w") as f:
            f.write(f"Timing Sync Failed at {datetime.now()}\n\n")
            f.write(f"Error Details:\n{error_details}\n\n")
            f.write("Environment Variables Set:\n")
            f.write(f"TIMING_API_TOKEN: {'Set' if TIMING_API_TOKEN else 'Not Set'}\n")
            f.write(f"NOTION_API_TOKEN: {'Set' if NOTION_API_TOKEN else 'Not Set'}\n")
            f.write(
                f"NOTION_DATABASE_ID: {'Set' if NOTION_DATABASE_ID else 'Not Set'}\n"
            )
    except Exception as e:
        print(f"Failed to create error file: {e}")


def log_error(error_message):
    """Log error to file, keeping only last MAX_ERROR_ENTRIES"""
    try:
        # Read existing errors
        errors = deque(maxlen=MAX_ERROR_ENTRIES)
        if ERROR_LOG_FILE.exists():
            with open(ERROR_LOG_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        errors.append(line)

        # Add new error
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        errors.append(f"{timestamp} - ERROR: {error_message}")

        # Write back
        with open(ERROR_LOG_FILE, "w") as f:
            for error in errors:
                f.write(error + "\n")
    except Exception as e:
        print(f"Failed to log error: {e}")


def handle_error(error_message, error_details=None, critical=False):
    """Handle errors with notifications, file creation, and logging"""
    print(f"ERROR: {error_message}")
    if error_details:
        print(f"Details: {error_details}")

    # Log the error
    log_error(error_message)

    # Only create desktop error file for critical errors
    if critical:
        full_details = f"{error_message}\n\n{error_details if error_details else 'No additional details'}\n\n{traceback.format_exc()}"
        create_error_file(full_details)


# Validate tokens exist
if not TIMING_API_TOKEN or not NOTION_API_TOKEN or not NOTION_DATABASE_ID:
    error_msg = "Please set TIMING_API_TOKEN, NOTION_API_TOKEN, and NOTION_DATABASE_ID environment variables"
    handle_error(error_msg, critical=True)
    # Let script complete normally instead of exiting with error


def get_local_timezone_offset():
    """Get local timezone offset in ISO 8601 format (e.g., '-05:00' for EST)"""
    offset = datetime.now().astimezone().strftime("%z")
    return f"{offset[:3]}:{offset[3:]}"


def resolve_database_id(project_path: str) -> str:
    """Return the Notion database ID for a project path.

    Multi-database routing: the top-level folder (first segment of the
    hierarchy path) is looked up in PROJECT_DB_MAP; if found, its database is
    used. Otherwise the default NOTION_DATABASE_ID applies.
    """
    if not project_path:
        return NOTION_DATABASE_ID
    root = project_path.split(" > ")[0].strip()
    return PROJECT_DB_MAP.get(root, NOTION_DATABASE_ID)


def resolve_workspace(project_path: str) -> Dict[str, Any]:
    """Resolve the (token, database_id, name) target for a project path.

    Multi-workspace routing: the top-level folder is looked up in
    WORKSPACE_MAP. If found, the workspace's API token (from its token_env)
    and per-workspace database map apply. Otherwise the default workspace
    (NOTION_API_TOKEN + PROJECT_DB_MAP / NOTION_DATABASE_ID) is used.

    Returns a dict with keys ``token``, ``database_id`` and ``name``.
    """
    if not project_path:
        return {
            "token": NOTION_API_TOKEN,
            "database_id": NOTION_DATABASE_ID,
            "name": "default",
        }

    root = project_path.split(" > ")[0].strip()
    ws_name = WORKSPACE_MAP.get(root)
    if ws_name and ws_name in WORKSPACES:
        ws = WORKSPACES[ws_name]
        token = os.environ.get(ws.get("token_env", ""), NOTION_API_TOKEN)
        ws_dbs = ws.get("databases", {})
        db_id = ws_dbs.get(root, resolve_database_id(project_path))
        return {"token": token, "database_id": db_id, "name": ws_name}

    return {
        "token": NOTION_API_TOKEN,
        "database_id": resolve_database_id(project_path),
        "name": "default",
    }


def seconds_to_duration_string(seconds):
    """Convert seconds to H:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _safe_custom_fields(raw: Any) -> Dict[str, str]:
    """Return a stable dict of string custom_fields from a Timing entry.

    Timing custom_fields are string key/value pairs. Values are coerced to str
    defensively; any non-string value is skipped.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, str):
            out[str(k)] = v
    return out


def _custom_fields_summary(custom_fields: Dict[str, str], limit: int = 2000) -> str:
    """Render custom_fields into a single readable string.

    Device-scoped enrichment keys (e.g. ``dayflow_flexmbp``) are kept as
    ``key: value`` pairs separated by " | ". Truncated at ``limit`` chars so
    long enrichment payloads don't blow up a Notion rich_text property.
    """
    if not custom_fields:
        return ""
    parts = [f"{k}: {v}" for k, v in custom_fields.items()]
    text = " | ".join(parts)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


# =============================================================================
# TIMING API - Enhanced with Entry-Level Data
# =============================================================================


def get_timing_entries(date: str) -> List[Dict]:
    """
    Fetch individual time entries from Timing API.
    Uses /time-entries endpoint for granular data.

    Args:
        date: Date in YYYY-MM-DD format

    Returns:
        List of time entry objects with full details
    """
    tz_offset = get_local_timezone_offset()
    start_time = f"{date}T00:00:00{tz_offset}"
    end_time = f"{date}T23:59:59{tz_offset}"

    url = "https://web.timingapp.com/api/v1/time-entries"
    headers = {
        "Authorization": f"Bearer {TIMING_API_TOKEN}",
        "Accept": "application/json",
    }
    params = {
        "start_date_min": start_time,
        "start_date_max": end_time,
        "include_project_data": "true",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to fetch Timing entries: {str(e)}"
        handle_error(error_msg)
        raise


def process_timing_entries(entries: List[Dict]) -> Dict[str, Any]:
    """
    Process timing entries into project totals and entry details.

    Returns dict with:
    - project_totals: Dict of project -> {duration, entries}
    - entry_details: List of individual entries with metadata
    - total_seconds: Total time tracked
    """
    project_totals = {}
    entry_details = []
    total_seconds = 0

    for entry in entries:
        duration = entry.get("duration", 0)
        if duration <= 0:
            continue

        total_seconds += duration

        # Extract project info
        project_data = entry.get("project")
        if project_data is None:
            project_name = "Uncategorized"
            project_path = "Uncategorized"
        elif isinstance(project_data, dict):
            title_chain = project_data.get("title_chain", [])
            if title_chain:
                project_path = " > ".join(title_chain)
                project_name = title_chain[-1]  # Leaf project name
            else:
                project_name = project_data.get("title", "Unknown")
                project_path = project_name
        else:
            project_name = str(project_data)
            project_path = project_name

        # Build entry detail
        entry_detail = {
            "title": entry.get("title", ""),
            "notes": entry.get("notes", ""),
            "duration_seconds": duration,
            "duration_hours": round(duration / 3600, 3),
            "start_time": entry.get("start_date", ""),
            "end_time": entry.get("end_date", ""),
            "project_name": project_name,
            "project_path": project_path,
            "is_running": entry.get("is_running", False),
            "custom_fields": _safe_custom_fields(entry.get("custom_fields")),
        }
        entry_details.append(entry_detail)

        # Aggregate by project path (full hierarchy)
        if project_path not in project_totals:
            project_totals[project_path] = {
                "project_name": project_name,
                "total_duration": 0,
                "entry_count": 0,
                "entries": [],
            }
        project_totals[project_path]["total_duration"] += duration
        project_totals[project_path]["entry_count"] += 1
        project_totals[project_path]["entries"].append(entry_detail)

    return {
        "project_totals": project_totals,
        "entry_details": entry_details,
        "total_seconds": total_seconds,
    }


# =============================================================================
# SCREENTIME - macOS ScreenTime SQLite Integration
# =============================================================================


def get_screentime_data(date: str) -> Optional[Dict[str, Any]]:
    """Query app-usage data for the given date.

    Source is selected by SCREENTIME_SOURCE:
    - "timing": Timing.app's own SQLite AppActivity table (FDA-free, works
      under launchd/cron).
    - "knowledgec": Apple's knowledgeC.db (requires Full Disk Access).

    Returns:
        Dict with app usage data, or None if unavailable.
    """
    if SCREENTIME_SOURCE == "timing":
        return _get_screentime_appactivity(date)
    return _get_screentime_knowledgec(date)


def _get_screentime_knowledgec(date: str) -> Optional[Dict[str, Any]]:
    """Query Apple's knowledgeC.db (requires Full Disk Access)."""
    if not SCREENTIME_DB.exists():
        print(f"ScreenTime database not found at {SCREENTIME_DB}")
        return None

    try:
        conn = sqlite3.connect(f"file:{SCREENTIME_DB}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Query app usage for the specific date
        # ScreenTime uses Core Data timestamps (seconds since 2001-01-01)
        query = """
        SELECT 
            ZOBJECT.ZVALUESTRING as app_bundle_id,
            COUNT(*) as event_count,
            ROUND(SUM(ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) / 60.0, 1) as duration_minutes,
            ROUND(SUM(ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) / 3600.0, 2) as duration_hours
        FROM ZOBJECT
        WHERE ZOBJECT.ZSTREAMNAME = '/app/usage'
        AND date(ZOBJECT.ZSTARTDATE + 978307200, 'unixepoch', 'localtime') = ?
        GROUP BY ZOBJECT.ZVALUESTRING
        ORDER BY duration_minutes DESC;
        """

        cursor.execute(query, (date,))
        rows = cursor.fetchall()

        # Calculate totals
        total_events = 0
        total_minutes = 0
        apps = []

        for row in rows:
            bundle_id, events, minutes, hours = row
            if minutes and minutes > 0:
                total_events += events
                total_minutes += minutes
                apps.append(
                    {
                        "bundle_id": bundle_id or "unknown",
                        "app_name": _bundle_to_app_name(bundle_id),
                        "event_count": events,
                        "duration_minutes": minutes,
                        "duration_hours": hours,
                    }
                )

        conn.close()

        # Get top N apps for summary
        top_apps = apps[:SCREENTIME_TOP_APPS]
        top_apps_summary = ", ".join(
            f"{app['app_name']} ({app['duration_hours']}h)" for app in top_apps
        )

        return {
            "total_events": total_events,
            "total_minutes": round(total_minutes, 1),
            "total_hours": round(total_minutes / 60, 2),
            "app_count": len(apps),
            "apps": apps,
            "top_apps": top_apps,
            "top_apps_summary": top_apps_summary,
        }

    except sqlite3.OperationalError as e:
        if "authorization denied" in str(e).lower():
            print("ScreenTime access denied - Full Disk Access required")
            print(
                "Grant access: System Settings → Privacy & Security → Full Disk Access"
            )
        else:
            print(f"ScreenTime database error: {e}")
        return None
    except Exception as e:
        print(f"Failed to query ScreenTime: {e}")
        return None


def _get_screentime_appactivity(date: str) -> Optional[Dict[str, Any]]:
    """Query Timing.app's SQLite AppActivity table for app-usage data.

    FDA-free alternative to knowledgeC.db: Timing.app's own local database
    (~/Library/Application Support/info.eurocomp.Timing2/SQLite.db) records
    per-app activity (AppActivity) with project attribution and per-device
    scoping, and is readable by unattended processes (launchd/cron) without
    Full Disk Access.

    Args:
        date: Date in YYYY-MM-DD format.

    Returns:
        Dict with app usage data, or None if unavailable.
    """
    if not TIMING_SQLITE_DB.exists():
        print(f"Timing SQLite database not found at {TIMING_SQLITE_DB}")
        return None

    # Local device scoping: AppActivity rows carry localDeviceID; find this
    # Mac's device and restrict to it so we see this device's usage only.
    # Falls back to all devices if the device map can't be read.
    try:
        conn = sqlite3.connect(f"file:{TIMING_SQLITE_DB}?mode=ro", uri=True)
        cursor = conn.cursor()

        local_device_id = _resolve_local_device_id(cursor)

        # AppActivity stores startDate/endDate as Unix epoch seconds.
        # Filter to the requested local date and (optionally) this device.
        query = """
        SELECT ap.title AS app_title,
               ROUND(SUM(a.endDate - a.startDate), 0) AS secs
        FROM AppActivity a
        JOIN Application ap ON a.applicationID = ap.id
        LEFT JOIN Project p ON a.projectID = p.id
        WHERE a.isDeleted = 0
          AND date(a.endDate, 'unixepoch', 'localtime') = ?
        """
        params: List[Any] = [date]
        if local_device_id:
            query += " AND a.localDeviceID = ?"
            params.append(local_device_id)
        query += """
        GROUP BY ap.title
        ORDER BY secs DESC;
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Failed to query Timing AppActivity: {e}")
        return None

    total_events = 0
    total_seconds = 0
    apps = []
    for app_title, secs in rows:
        secs = int(secs or 0)
        if secs <= 0:
            continue
        minutes = round(secs / 60.0, 1)
        hours = round(secs / 3600.0, 2)
        total_events += 1
        total_seconds += secs
        apps.append(
            {
                "bundle_id": app_title or "unknown",
                "app_name": _bundle_to_app_name(app_title),
                "event_count": 1,
                "duration_minutes": minutes,
                "duration_hours": hours,
            }
        )

    top_apps = apps[:SCREENTIME_TOP_APPS]
    top_apps_summary = ", ".join(
        f"{app['app_name']} ({app['duration_hours']}h)" for app in top_apps
    )

    return {
        "total_events": total_events,
        "total_minutes": round(total_seconds / 60.0, 1),
        "total_hours": round(total_seconds / 3600.0, 2),
        "app_count": len(apps),
        "apps": apps,
        "top_apps": top_apps,
        "top_apps_summary": top_apps_summary,
    }


def _resolve_local_device_id(cursor) -> Optional[str]:
    """Return this machine's localDeviceID from Timing's Device table.

    Falls back to None (all devices) if the table or a match can't be found.
    """
    try:
        cursor.execute(
            "SELECT localID FROM Device WHERE displayName = ?",
            (Path.home().name,),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])
    except Exception:
        pass
    return None


def _bundle_to_app_name(bundle_id: str) -> str:
    """Convert bundle ID to human-readable app name."""
    if not bundle_id:
        return "Unknown"

    # Common bundle ID mappings
    mappings = {
        "com.apple.Safari": "Safari",
        "com.apple.mail": "Mail",
        "com.apple.MobileSMS": "Messages",
        "com.apple.finder": "Finder",
        "com.apple.Terminal": "Terminal",
        "com.googlecode.iterm2": "iTerm",
        "com.microsoft.VSCode": "VS Code",
        "com.tinyspeck.slackmacgap": "Slack",
        "com.apple.Notes": "Notes",
        "com.apple.iCal": "Calendar",
        "us.zoom.xos": "Zoom",
        "com.google.Chrome": "Chrome",
        "com.apple.Music": "Music",
        "notion.id": "Notion",
        "com.linear": "Linear",
        "com.1password.1password": "1Password",
        "com.timingapp.timing": "Timing",
    }

    if bundle_id in mappings:
        return mappings[bundle_id]

    # Extract app name from bundle ID
    parts = bundle_id.split(".")
    if len(parts) >= 3:
        return parts[-1].replace("-", " ").title()
    return bundle_id


# =============================================================================
# NOTION API - Enhanced Properties
# =============================================================================


def find_notion_page(
    date: str,
    project: str,
    database_id: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Find existing Notion page with matching date and project.

    Args:
        database_id: Target Notion database. Defaults to NOTION_DATABASE_ID.
        token: Notion API token for the target workspace. Defaults to
            NOTION_API_TOKEN (multi-workspace routing).
    """
    db_id = database_id or NOTION_DATABASE_ID
    auth_token = token or NOTION_API_TOKEN
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    data = {
        "filter": {
            "and": [
                {"property": "Date", "date": {"equals": date}},
                {"property": "Project", "title": {"equals": project}},
            ]
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        results = response.json()["results"]
        return results[0]["id"] if results else None
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to query Notion database: {str(e)}"
        handle_error(error_msg)
        raise


def update_or_create_notion_page(
    page_id: Optional[str],
    date: str,
    duration_seconds: float,
    project: str,
    entry_count: int = 0,
    top_entries: Optional[List[str]] = None,
    screentime_data: Optional[Dict] = None,
    database_id: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """
    Update existing page or create new one in Notion.

    Enhanced with optional entry details and ScreenTime data.

    Args:
        database_id: Target Notion database. Defaults to NOTION_DATABASE_ID.
        token: Notion API token for the target workspace. Defaults to
            NOTION_API_TOKEN (multi-workspace routing).
    """
    db_id = database_id or NOTION_DATABASE_ID
    auth_token = token or NOTION_API_TOKEN
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    # Convert duration
    duration_string = seconds_to_duration_string(duration_seconds)
    duration_hours = round(duration_seconds / 3600, 3)

    properties = {
        "Date": {"date": {"start": date}},
        "Project": {"title": [{"text": {"content": project}}]},
        "Duration": {"rich_text": [{"text": {"content": duration_string}}]},
        "Hours": {"number": duration_hours},
        "Last Sync": {
            "date": {
                "start": datetime.now().strftime(
                    f"%Y-%m-%dT%H:%M:%S{get_local_timezone_offset()}"
                )
            }
        },
    }

    # Add entry count if available (requires "Entry Count" number property in Notion)
    if entry_count > 0:
        properties["Entry Count"] = {"number": entry_count}

    # Add top entries summary if available (requires "Top Entries" rich_text property)
    if top_entries:
        entries_text = " | ".join(top_entries[:3])  # Top 3 entries
        if len(entries_text) > 2000:
            entries_text = entries_text[:1997] + "..."
        properties["Top Entries"] = {"rich_text": [{"text": {"content": entries_text}}]}

    # Add ScreenTime data if available (requires corresponding properties)
    if screentime_data:
        properties["Active Hours"] = {"number": screentime_data.get("total_hours", 0)}
        properties["Screen Events"] = {"number": screentime_data.get("total_events", 0)}
        if screentime_data.get("top_apps_summary"):
            summary = screentime_data["top_apps_summary"]
            if len(summary) > 2000:
                summary = summary[:1997] + "..."
            properties["Top Apps"] = {"rich_text": [{"text": {"content": summary}}]}

    if page_id:
        # Update existing page
        url = f"https://api.notion.com/v1/pages/{page_id}"
        data = {"properties": properties}
        method = "PATCH"
    else:
        # Create new page
        url = "https://api.notion.com/v1/pages"
        data = {"parent": {"database_id": db_id}, "properties": properties}
        method = "POST"

    response = None
    try:
        response = requests.request(method, url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return page_id if page_id else result.get("id")
    except requests.exceptions.RequestException as e:
        error_msg = (
            f"Failed to {'update' if page_id else 'create'} Notion page: {str(e)}"
        )
        if response is not None and response.status_code == 400:
            response_json = response.json()
            if "validation_error" in str(response_json):
                print("Note: Some enhanced properties not available in Notion database")
                return _sync_basic_properties(
                    page_id,
                    date,
                    duration_seconds,
                    project,
                    database_id=db_id,
                    token=auth_token,
                )
        handle_error(error_msg)
        raise


def update_page_content_with_entries(
    page_id: str, entries: List[Dict], token: Optional[str] = None
) -> bool:
    """Replace page content with formatted entry details as bullet list blocks."""
    if not entries:
        return True

    auth_token = token or NOTION_API_TOKEN
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"

    try:
        response = requests.get(blocks_url, headers=headers, timeout=30)
        response.raise_for_status()
        for block in response.json().get("results", []):
            requests.delete(
                f"https://api.notion.com/v1/blocks/{block['id']}",
                headers=headers,
                timeout=30,
            )
    except Exception:
        pass

    children = [
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": "Time Entries"}}]
            },
        }
    ]

    sorted_entries = sorted(entries, key=lambda x: x["duration_seconds"], reverse=True)

    for entry in sorted_entries:
        title = entry.get("title") or "(no title)"
        duration = seconds_to_duration_string(entry["duration_seconds"])
        notes = entry.get("notes", "")
        start = entry.get("start_time", "")

        time_str = ""
        if start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M")
            except Exception:
                pass

        bullet_text = f"{title} ({duration})"
        if time_str:
            bullet_text += f" @{time_str}"

        bullet_block = {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": bullet_text}}]
            },
        }

        if notes:
            bullet_block["bulleted_list_item"]["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": notes},
                                "annotations": {"italic": True, "color": "gray"},
                            }
                        ]
                    },
                }
            ]

        # Propagate device-scoped custom_fields (enrichment markers) into the
        # page content when enabled. Only present fields are shown; absent
        # custom_fields simply yield no sub-block. Kept out of the visible
        # Project/Duration/Date columns so timesheet views stay clean.
        if SYNC_CUSTOM_FIELDS:
            cf_summary = _custom_fields_summary(entry.get("custom_fields") or {})
            if cf_summary:
                cf_block = {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": cf_summary},
                                "annotations": {"italic": True, "color": "green"},
                            }
                        ]
                    },
                }
                children_key = "bulleted_list_item"
                children_list = bullet_block[children_key].setdefault("children", [])
                children_list.append(cf_block)

        children.append(bullet_block)

    try:
        response = requests.patch(
            blocks_url, headers=headers, json={"children": children}, timeout=30
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to update page content: {e}")
        return False


def _sync_basic_properties(
    page_id: Optional[str],
    date: str,
    duration_seconds: float,
    project: str,
    database_id: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Fallback to basic properties only (backward compatible)."""
    db_id = database_id or NOTION_DATABASE_ID
    auth_token = token or NOTION_API_TOKEN
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    duration_string = seconds_to_duration_string(duration_seconds)
    duration_hours = round(duration_seconds / 3600, 3)

    properties = {
        "Date": {"date": {"start": date}},
        "Project": {"title": [{"text": {"content": project}}]},
        "Duration": {"rich_text": [{"text": {"content": duration_string}}]},
        "Hours": {"number": duration_hours},
        "Last Sync": {
            "date": {
                "start": datetime.now().strftime(
                    f"%Y-%m-%dT%H:%M:%S{get_local_timezone_offset()}"
                )
            }
        },
    }

    if page_id:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        data = {"properties": properties}
        method = "PATCH"
    else:
        url = "https://api.notion.com/v1/pages"
        data = {"parent": {"database_id": db_id}, "properties": properties}
        method = "POST"

    response = requests.request(method, url, headers=headers, json=data, timeout=30)
    response.raise_for_status()
    result = response.json()
    return page_id if page_id else result.get("id")


# =============================================================================
# MAIN SYNC LOGIC
# =============================================================================


def main():
    """Main sync function with enhanced data collection"""
    print(f"Starting Timing to Notion sync at {datetime.now()}")
    print(f"Sync modes: entries={SYNC_ENTRIES}, screentime={SYNC_SCREENTIME}")

    # Skip when the system is idle, unless SYNC_WHEN_IDLE is set or idle can't
    # be determined. Threshold is IDLE_THRESHOLD_SECONDS (default 300).
    if not SYNC_WHEN_IDLE:
        try:
            idle_time = (
                int(
                    os.popen("ioreg -c IOHIDSystem | grep HIDIdleTime").read().split("=")[1]
                )
                / 1000000000
            )
            if idle_time > IDLE_THRESHOLD_SECONDS:
                print(
                    f"Computer idle for {idle_time:.0f} seconds, skipping sync "
                    f"(set SYNC_WHEN_IDLE=true to sync anyway)"
                )
                sys.exit(0)
        except Exception:
            # If we can't check idle time, continue with sync
            pass

    try:
        today = datetime.now().strftime("%Y-%m-%d")
        tz_offset = get_local_timezone_offset()
        print(f"Fetching data for {today} ({tz_offset})")

        # Fetch timing entries
        entries = get_timing_entries(today)
        print(f"API returned {len(entries)} time entries for {today}")

        if not entries:
            print("No time entries found for today")
            return

        # Process entries
        processed = process_timing_entries(entries)
        project_totals = processed["project_totals"]
        entry_details = processed["entry_details"]
        total_seconds = processed["total_seconds"]

        # Fetch ScreenTime data if enabled
        screentime_data = None
        if SYNC_SCREENTIME:
            print("Fetching ScreenTime data...")
            screentime_data = get_screentime_data(today)
            if screentime_data:
                print(
                    f"ScreenTime: {screentime_data['total_hours']}h active, {screentime_data['app_count']} apps"
                )
            else:
                print("ScreenTime data unavailable (check Full Disk Access)")

        # Print entry details if enabled
        if SYNC_ENTRIES:
            print(f"\nIndividual entries ({len(entry_details)}):")
            for entry in entry_details:
                title = entry["title"] or "(no title)"
                print(
                    f"  {entry['project_path']}: {title} - {seconds_to_duration_string(entry['duration_seconds'])}"
                )

        print(f"\nGrouped by project ({len(project_totals)}):")
        updated_count = 0
        created_count = 0

        # Process each project
        for project_path, project_info in project_totals.items():
            total_duration = project_info["total_duration"]
            entry_count = project_info["entry_count"]

            # Get top entry titles for summary
            top_entries = []
            for entry in sorted(
                project_info["entries"],
                key=lambda x: x["duration_seconds"],
                reverse=True,
            )[:3]:
                if entry["title"]:
                    top_entries.append(
                        f"{entry['title']} ({seconds_to_duration_string(entry['duration_seconds'])})"
                    )

            print(
                f"  {project_path}: {seconds_to_duration_string(total_duration)} ({entry_count} entries)"
            )

            # Multi-database / multi-workspace routing: resolve the target
            # Notion workspace (token) and database for this project's
            # top-level folder. Defaults preserve existing behaviour.
            ws = resolve_workspace(project_path)
            ws_token = ws["token"]
            db_id = ws["database_id"]
            ws_name = ws["name"]

            try:
                existing_page_id = find_notion_page(
                    today, project_path, database_id=db_id, token=ws_token
                )

                result_page_id = update_or_create_notion_page(
                    page_id=existing_page_id,
                    date=today,
                    duration_seconds=total_duration,
                    project=project_path,
                    entry_count=entry_count,
                    top_entries=top_entries if SYNC_ENTRIES else None,
                    screentime_data=screentime_data,
                    database_id=db_id,
                    token=ws_token,
                )

                if SYNC_ENTRIES and result_page_id:
                    update_page_content_with_entries(
                        result_page_id, project_info["entries"], token=ws_token
                    )

                if existing_page_id:
                    updated_count += 1
                    print(f"Updated: {project_path}")
                else:
                    created_count += 1
                    print(f"Created: {project_path}")
            except Exception as e:
                print(f"Failed to sync project {project_path}: {e}")
                continue

        # Summary
        total_hours = total_seconds / 3600
        print(f"\nSync complete: {updated_count} updated, {created_count} created")
        print(
            f"Total time tracked today: {seconds_to_duration_string(total_seconds)} ({total_hours:.2f} hours)"
        )

        if screentime_data:
            print(
                f"ScreenTime active: {screentime_data['total_hours']}h ({screentime_data['total_events']} events)"
            )
            print(f"Top apps: {screentime_data['top_apps_summary']}")

    except Exception as e:
        error_msg = f"Sync failed: {str(e)}"
        handle_error(error_msg, traceback.format_exc())
        # Let script complete normally instead of exiting with error


if __name__ == "__main__":
    main()
