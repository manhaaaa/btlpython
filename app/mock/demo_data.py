"""
Mock demo data module for Android and simulation mode.
Provides simulated users, access logs, and door events without requiring database or serial hardware.
"""
from datetime import datetime
from typing import List, Dict, Any

_DEMO_USERS = [
    {"id": "USR001", "name": "Nguyễn Văn A", "role": "user", "pin": "1234"},
    {"id": "USR002", "name": "Trần Thị B", "role": "user", "pin": "5678"},
    {"id": "ADM001", "name": "Quản Trị Viên", "role": "admin", "pin": "9999"},
]

_DEMO_LOGS = [
    {
        "timestamp": "2026-11-07 10:15:32",
        "event_type": "ACCESS",
        "status": "SUCCESS",
        "detail": "User: Nguyễn Văn A (USR001)",
        "raw_pin": "1234",
    },
    {
        "timestamp": "2026-11-07 10:45:11",
        "event_type": "ACCESS",
        "status": "FAILED",
        "detail": "Nguoi dung khong hop le hoac sai ma",
        "raw_pin": "0000",
    },
    {
        "timestamp": "2026-11-07 11:02:44",
        "event_type": "ACCESS",
        "status": "SUCCESS",
        "detail": "User: Trần Thị B (USR002)",
        "raw_pin": "5678",
    },
]


def get_demo_users() -> List[Dict[str, Any]]:
    """Returns the list of demo user profiles."""
    return list(_DEMO_USERS)


def get_demo_logs(limit: int = 25) -> List[Dict[str, Any]]:
    """Returns the most recent demo access logs."""
    return list(reversed(_DEMO_LOGS[-limit:]))


def clear_demo_logs() -> None:
    """Clears the in-memory demo logs."""
    _DEMO_LOGS.clear()


def generate_simulated_event(event_type: str = "SUCCESS") -> Dict[str, Any]:
    """
    Generates a simulated door access event and adds it to the demo logs.
    Supported types: 'SUCCESS', 'FAILED', 'LOCKOUT'.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if event_type == "SUCCESS":
        entry = {
            "timestamp": now_str,
            "event_type": "ACCESS",
            "status": "SUCCESS",
            "detail": "User: Demo User (Mô phỏng thành công)",
            "raw_pin": "1234",
        }
    elif event_type == "LOCKOUT":
        entry = {
            "timestamp": now_str,
            "event_type": "ALARM",
            "status": "LOCKOUT",
            "detail": "Kích hoạt khóa tạm 30.0s (Mô phỏng)",
            "raw_pin": "9999",
        }
    else:
        entry = {
            "timestamp": now_str,
            "event_type": "ACCESS",
            "status": "FAILED",
            "detail": "Mã PIN không đúng (Mô phỏng)",
            "raw_pin": "0000",
        }
    _DEMO_LOGS.append(entry)
    return entry
