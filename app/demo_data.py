"""
Android Demo Data Module for Smart PIN Door Lock System
Provides mock user profiles and simulated access event logs for Android demo / monitoring mode.

SECURITY CONSTRAINTS:
- Absolutely NO real PINs (all PINs masked as '****').
- Absolutely NO imports from data/ directory or real database.
- Completely self-contained for Android APK packaging.
"""

import sys
import os
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Ensure bytecode is never written
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Simulated mock user profiles for Android demo mode
DEMO_USERS: List[Dict[str, Any]] = [
    {
        "id": "DEMO001",
        "name": "Nguyễn Văn Demo",
        "role": "user",
        "pin": "****",
    },
    {
        "id": "DEMO002",
        "name": "Trần Thị Thử Nghiệm",
        "role": "user",
        "pin": "****",
    },
    {
        "id": "DEMO003",
        "name": "Lê Hoàng Khảo Sát",
        "role": "user",
        "pin": "****",
    },
    {
        "id": "DEMO_ADM",
        "name": "Quản Trị Viên Android",
        "role": "admin",
        "pin": "****",
    },
]

# Baseline simulated log events
_INITIAL_LOGS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "timestamp": (datetime.now() - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": "ACCESS",
        "status": "SUCCESS",
        "detail": "User: Nguyễn Văn Demo (DEMO001) | PIN: ****",
    },
    {
        "id": 2,
        "timestamp": (datetime.now() - timedelta(minutes=18)).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": "ACCESS",
        "status": "FAILED",
        "detail": "Nguoi dung khong hop le hoac sai ma | PIN: ****",
    },
    {
        "id": 3,
        "timestamp": (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": "ACCESS",
        "status": "SUCCESS",
        "detail": "User: Trần Thị Thử Nghiệm (DEMO002) | PIN: ****",
    },
    {
        "id": 4,
        "timestamp": (datetime.now() - timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": "ALARM",
        "status": "LOCKOUT",
        "detail": "Kich hoat khoa tam 30.0s sau 3 lan nhap sai | PIN: ****",
    },
    {
        "id": 5,
        "timestamp": (datetime.now() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": "ACCESS",
        "status": "SUCCESS",
        "detail": "User: Quản Trị Viên Android (DEMO_ADM) | PIN: ****",
    },
]

# In-memory working copy of demo logs
_active_demo_logs: List[Dict[str, Any]] = [dict(log) for log in _INITIAL_LOGS]
_log_id_counter: int = len(_INITIAL_LOGS) + 1


def get_demo_users() -> List[Dict[str, Any]]:
    """Returns the list of simulated user profiles with masked PINs."""
    return [dict(u) for u in DEMO_USERS]


def get_demo_logs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Returns simulated event logs in descending chronological order (newest first).
    """
    sorted_logs = sorted(_active_demo_logs, key=lambda x: x["id"], reverse=True)
    if limit is not None:
        return sorted_logs[:limit]
    return sorted_logs


def generate_simulated_event(event_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Generates a new simulated event for Android demo interactive feed.
    event_type can be 'SUCCESS', 'FAILED', or 'LOCKOUT'.
    """
    global _log_id_counter

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if event_type is None:
        event_type = random.choice(["SUCCESS", "SUCCESS", "FAILED", "LOCKOUT"])

    new_id = _log_id_counter
    _log_id_counter += 1

    if event_type == "SUCCESS":
        user = random.choice(DEMO_USERS)
        event = {
            "id": new_id,
            "timestamp": now_str,
            "event_type": "ACCESS",
            "status": "SUCCESS",
            "detail": f"User: {user['name']} ({user['id']}) | PIN: ****",
        }
    elif event_type == "FAILED":
        event = {
            "id": new_id,
            "timestamp": now_str,
            "event_type": "ACCESS",
            "status": "FAILED",
            "detail": "Nguoi dung khong hop le hoac sai ma | PIN: ****",
        }
    else:  # LOCKOUT
        event = {
            "id": new_id,
            "timestamp": now_str,
            "event_type": "ALARM",
            "status": "LOCKOUT",
            "detail": "Kich hoat khoa tam 30.0s sau 3 lan nhap sai | PIN: ****",
        }

    _active_demo_logs.append(event)
    return event


def clear_demo_logs() -> None:
    """Clears all demo event logs."""
    _active_demo_logs.clear()


def reset_demo_data() -> None:
    """Resets demo logs to the initial simulated state."""
    global _active_demo_logs, _log_id_counter
    _active_demo_logs = [dict(log) for log in _INITIAL_LOGS]
    _log_id_counter = len(_INITIAL_LOGS) + 1
