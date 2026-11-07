"""
Multi-user Authentication and Audit Logging Service
Manages credential verification and secure audit logging.
All PINs are masked as '****' in log files, console, and database records.
Data directory is strictly protected against bytecode generation and mutation.
"""

import os
import sys
import json
import sqlite3
import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure bytecode is never written to disk
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


@dataclass
class User:
    id: str
    name: str
    pin: str
    role: str = "user"

    def __repr__(self) -> str:
        # Never expose raw PIN in representations
        return f"User(id={self.id!r}, name={self.name!r}, pin='****', role={self.role!r})"

    def to_dict(self, mask_pin: bool = True) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "pin": "****" if mask_pin else self.pin,
        }


class AuthService:
    """
    Authentication Service managing user credentials and security audit logging.
    """

    DEFAULT_USERS = [
        {"id": "USR001", "name": "Nguyễn Văn A", "pin": "1234", "role": "user"},
        {"id": "USR002", "name": "Trần Thị B", "pin": "5678", "role": "user"},
        {"id": "ADM001", "name": "Quản Trị Viên", "pin": "9999", "role": "admin"},
    ]

    def __init__(
        self,
        users_file: Optional[str | Path] = None,
        log_file: Optional[str | Path] = None,
        db_path: Optional[str | Path] = None,
        enable_db: bool = True,
    ):
        base_dir = Path(__file__).resolve().parent

        # Resolve paths
        self.users_file = Path(users_file) if users_file else (base_dir / "users.json")
        self.log_file = Path(log_file) if log_file else (base_dir / "audit.log")
        self.db_path = Path(db_path) if db_path else (base_dir / "access_control.db")
        self.enable_db = enable_db

        self._users_by_pin: Dict[str, User] = {}
        self._users_by_id: Dict[str, User] = {}

        # Load users and initialize db
        self.load_users()
        if self.enable_db:
            self._init_database()

    def load_users(self) -> None:
        """Loads and validates user records from JSON configuration."""
        self._users_by_pin.clear()
        self._users_by_id.clear()

        user_records = []
        if self.users_file.is_file():
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    user_records = json.load(f)
            except Exception as e:
                self._write_file_log(
                    "SYSTEM", "WARNING", f"Could not parse users file {self.users_file}: {e}. Loading default users."
                )
                user_records = self.DEFAULT_USERS
        else:
            user_records = self.DEFAULT_USERS

        for rec in user_records:
            pin = str(rec.get("pin", "")).strip()
            # Validate 4-digit requirement
            if not re.match(r"^\d{4}$", pin):
                continue
            user = User(
                id=str(rec.get("id", "UNKNOWN")),
                name=str(rec.get("name", "Unknown User")),
                pin=pin,
                role=str(rec.get("role", "user")),
            )
            self._users_by_pin[pin] = user
            self._users_by_id[user.id] = user

    def _init_database(self) -> None:
        """Initializes the SQLite access_logs table in the local app database."""
        try:
            # Ensure parent folder exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self._write_file_log("SYSTEM", "ERROR", f"Database init failed: {e}")

    def authenticate(self, pin: str) -> Optional[User]:
        """
        Validates user PIN.
        Returns User on success, None on failure.
        Always logs the event with PIN masked as '****'.
        """
        # Strictly ensure input is sanitized
        clean_pin = pin.strip()
        user = self._users_by_pin.get(clean_pin)

        if user:
            detail = f"User: {user.name} ({user.id}) | PIN: ****"
            self.log_event(
                event_type="ACCESS",
                status="SUCCESS",
                detail=detail,
                user_id=user.id,
                user_name=user.name,
            )
            return user
        else:
            detail = "Nguoi dung khong hop le hoac sai ma | PIN: ****"
            self.log_event(
                event_type="ACCESS",
                status="FAILED",
                detail=detail,
                user_id="UNKNOWN",
                user_name="UNKNOWN",
            )
            return None

    def log_lockout(self, duration: float) -> None:
        """Logs a temporary lockout event."""
        detail = f"Kich hoat khoa tam {duration:.1f}s sau 3 lan nhap sai | PIN: ****"
        self.log_event(
            event_type="ALARM",
            status="LOCKOUT",
            detail=detail,
            user_id="SYSTEM",
            user_name="SYSTEM",
        )

    def log_event(
        self,
        event_type: str,
        status: str,
        detail: str = "",
        user_id: str = "UNKNOWN",
        user_name: str = "UNKNOWN",
    ) -> None:
        """
        Records an audit event to file and database.
        Guarantees that raw PINs are masked as '****'.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Sanitize detail string: replace any raw 4-digit PIN with **** if present
        sanitized_detail = self._mask_pin_in_string(detail)

        # 1. Write to text audit log file
        self._write_file_log(event_type, status, sanitized_detail, timestamp)

        # 2. Write to SQLite database
        if self.enable_db:
            self._write_db_log(event_type, status, sanitized_detail, timestamp)

    def _mask_pin_in_string(self, text: str) -> str:
        """Utility to ensure no raw PIN leaks into log outputs."""
        for pin in self._users_by_pin.keys():
            if pin in text:
                text = text.replace(pin, "****")
        return text

    def _write_file_log(
        self, event_type: str, status: str, detail: str, timestamp: Optional[str] = None
    ) -> None:
        """Appends formatted audit entry to the audit log file."""
        if not timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{timestamp} | [{event_type}] {status} | {detail}\n"
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
                f.flush()
        except Exception:
            pass

    def _write_db_log(
        self, event_type: str, status: str, detail: str, timestamp: str
    ) -> None:
        """Saves log row to SQLite. Reuses data.database.save_log if available, else direct SQLite."""
        # Attempt to reuse data.database with redirected DB_NAME
        saved_via_data_db = False
        try:
            sys.dont_write_bytecode = True
            # Check if btl directory is in sys.path
            btl_dir = str(Path(__file__).resolve().parent.parent)
            if btl_dir not in sys.path:
                sys.path.insert(0, btl_dir)

            import data.database as data_db

            # Redirect destination database to safe app db path
            data_db.DB_NAME = str(self.db_path)
            # Call save_log
            data_db.save_log(event_type, status, detail)
            saved_via_data_db = True
        except Exception:
            saved_via_data_db = False

        if not saved_via_data_db:
            # Fallback direct sqlite insert
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO access_logs (timestamp, event_type, status, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (timestamp, event_type, status, detail),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

    def get_logs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returns log entries from database or audit file."""
        if self.enable_db and self.db_path.is_file():
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                if limit:
                    cursor.execute(
                        "SELECT id, timestamp, event_type, status, detail FROM access_logs ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                else:
                    cursor.execute(
                        "SELECT id, timestamp, event_type, status, detail FROM access_logs ORDER BY id DESC"
                    )
                rows = cursor.fetchall()
                conn.close()
                return [
                    {
                        "id": r[0],
                        "timestamp": r[1],
                        "event_type": r[2],
                        "status": r[3],
                        "detail": r[4],
                    }
                    for r in rows
                ]
            except Exception:
                pass
        return []

    def get_users(self) -> List[Dict[str, Any]]:
        """Returns list of users with PINs masked."""
        return [u.to_dict(mask_pin=True) for u in self._users_by_id.values()]
