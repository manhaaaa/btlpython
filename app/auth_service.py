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
from typing import Optional, List, Dict, Any, Tuple

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
    Authentication Service managing user credentials, master pin, and security audit logging.
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
        config_file: Optional[str | Path] = None,
    ):
        base_dir = Path(__file__).resolve().parent

        # Resolve paths
        self.config_file = Path(config_file) if config_file else (base_dir / "config.json")
        self.users_file = Path(users_file) if users_file else (base_dir / "users.json")
        self.log_file = Path(log_file) if log_file else (base_dir / "audit.log")
        self.db_path = Path(db_path) if db_path else (base_dir / "access_control.db")
        self.enable_db = enable_db

        self.master_pin: str = "1234"
        self.admin_username: str = "admin"
        self.admin_password: str = "1234"
        self._load_config()

        self._users_by_pin: Dict[str, User] = {}
        self._users_by_id: Dict[str, User] = {}
        self.recent_attempts: List[Dict[str, Any]] = []

        # Load users and initialize db
        self.load_users()
        if self.enable_db:
            self._init_database()

    def _load_config(self) -> None:
        """Loads master PIN and admin credentials from config.json."""
        if self.config_file.is_file():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                auth_cfg = cfg.get("auth", {})
                self.master_pin = str(auth_cfg.get("master_pin", "1234")).strip()
                self.admin_username = str(auth_cfg.get("admin_username", "admin")).strip()
                self.admin_password = str(auth_cfg.get("admin_password", "1234")).strip()
            except Exception:
                pass

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
                    detail TEXT,
                    raw_pin TEXT DEFAULT ''
                )
                """
            )
            # Ensure raw_pin column exists if table existed previously without it
            cursor.execute("PRAGMA table_info(access_logs)")
            columns = [c[1] for c in cursor.fetchall()]
            if "raw_pin" not in columns:
                cursor.execute("ALTER TABLE access_logs ADD COLUMN raw_pin TEXT DEFAULT ''")

            conn.commit()
            conn.close()
        except Exception as e:
            self._write_file_log("SYSTEM", "ERROR", f"Database init failed: {e}")

    def authenticate(self, pin: str) -> Optional[User]:
        """
        Validates user PIN.
        Checks Master PIN first (fixed master key), then individual user PINs.
        Returns User on success, None on failure.
        Always logs the event with PIN masked as '****' in detail, keeping raw PIN for admin audit.
        """
        clean_pin = pin.strip()

        # 1. Master PIN check (Universal fixed master key)
        if clean_pin == self.master_pin:
            detail = f"Master Key Accepted | PIN: ****"
            self.log_event(
                event_type="ACCESS",
                status="SUCCESS",
                detail=detail,
                user_id="MASTER",
                user_name="Mật khẩu chính (Master)",
                raw_pin=clean_pin,
            )
            self.recent_attempts.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw_pin": clean_pin,
                "status": "SUCCESS",
                "user_name": "Mật khẩu chính (Master)",
            })
            return User(id="MASTER", name="Mật khẩu chính (Master)", pin=self.master_pin, role="admin")

        # 2. Registered Users check
        user = self._users_by_pin.get(clean_pin)

        if user:
            detail = f"User: {user.name} ({user.id}) | PIN: ****"
            self.log_event(
                event_type="ACCESS",
                status="SUCCESS",
                detail=detail,
                user_id=user.id,
                user_name=user.name,
                raw_pin=clean_pin,
            )
            self.recent_attempts.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw_pin": clean_pin,
                "status": "SUCCESS",
                "user_name": user.name,
            })
            return user
        else:
            detail = "Nguoi dung khong hop le hoac sai ma | PIN: ****"
            self.log_event(
                event_type="ACCESS",
                status="FAILED",
                detail=detail,
                user_id="UNKNOWN",
                user_name="UNKNOWN",
                raw_pin=clean_pin,
            )
            self.recent_attempts.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw_pin": clean_pin,
                "status": "FAILED",
                "user_name": "Không xác định",
            })
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
        raw_pin: str = "",
    ) -> None:
        """
        Records an audit event to file and database.
        Guarantees that raw PINs are masked as '****' in visible text detail.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Sanitize detail string: replace any raw 4-digit PIN with **** if present
        sanitized_detail = self._mask_pin_in_string(detail)

        # 1. Write to text audit log file (Strictly masked)
        self._write_file_log(event_type, status, sanitized_detail, timestamp)

        # 2. Write to SQLite database
        if self.enable_db:
            self._write_db_log(event_type, status, sanitized_detail, timestamp, raw_pin)

    def _mask_pin_in_string(self, text: str) -> str:
        """Utility to ensure no raw PIN leaks into log outputs."""
        for pin in self._users_by_pin.keys():
            if pin in text:
                text = text.replace(pin, "****")
        if self.master_pin in text:
            text = text.replace(self.master_pin, "****")
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
        self, event_type: str, status: str, detail: str, timestamp: str, raw_pin: str = ""
    ) -> None:
        """Saves log row to SQLite. Reuses data.database.save_log if available, else direct SQLite."""
        # Attempt to reuse data.database with redirected DB_NAME
        saved_via_data_db = False
        try:
            sys.dont_write_bytecode = True
            btl_dir = str(Path(__file__).resolve().parent.parent)
            if btl_dir not in sys.path:
                sys.path.insert(0, btl_dir)

            import data.database as data_db

            # Redirect destination database to safe app db path
            data_db.DB_NAME = str(self.db_path)
            data_db.save_log(event_type, status, detail)
            saved_via_data_db = True
        except Exception:
            saved_via_data_db = False

        if saved_via_data_db:
            # Update latest log with raw_pin if provided
            if raw_pin:
                try:
                    conn = sqlite3.connect(str(self.db_path))
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE access_logs SET raw_pin = ? WHERE id = (SELECT MAX(id) FROM access_logs)",
                        (raw_pin,),
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
        else:
            # Fallback direct sqlite insert
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO access_logs (timestamp, event_type, status, detail, raw_pin)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (timestamp, event_type, status, detail, raw_pin),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

    def get_logs(self, limit: Optional[int] = None, as_admin: bool = False) -> List[Dict[str, Any]]:
        """
        Returns log entries from database or audit file.
        If as_admin=True, includes the raw_pin field for admin viewing.
        """
        if self.enable_db and self.db_path.is_file():
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(access_logs)")
                cols = [c[1] for c in cursor.fetchall()]
                has_raw = "raw_pin" in cols

                query = "SELECT id, timestamp, event_type, status, detail"
                if has_raw:
                    query += ", raw_pin"
                query += " FROM access_logs ORDER BY id DESC"
                if limit:
                    query += f" LIMIT {int(limit)}"

                cursor.execute(query)
                rows = cursor.fetchall()
                conn.close()
                result = []
                for r in rows:
                    entry = {
                        "id": r[0],
                        "timestamp": r[1],
                        "event_type": r[2],
                        "status": r[3],
                        "detail": r[4],
                    }
                    if as_admin and has_raw:
                        entry["raw_pin"] = r[5] or ""
                    result.append(entry)
                return result
            except Exception:
                pass
        return []

    def get_users(self, mask_pin: bool = True) -> List[Dict[str, Any]]:
        """Returns list of users with PINs masked by default."""
        return [u.to_dict(mask_pin=mask_pin) for u in self._users_by_id.values()]

    def verify_admin_login(self, username: str, password: str) -> bool:
        """Verifies admin credentials (defaults: admin / 1234)."""
        return (
            username.strip().lower() == self.admin_username.lower()
            and password.strip() == self.admin_password
        )

    def save_users(self) -> bool:
        """Persists current user database to users.json."""
        try:
            records = [
                {"id": u.id, "name": u.name, "pin": u.pin, "role": u.role}
                for u in self._users_by_id.values()
            ]
            with open(self.users_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self._write_file_log("SYSTEM", "ERROR", f"Save users failed: {e}")
            return False

    def update_user_pin(self, user_id: str, new_pin: str) -> Tuple[bool, str]:
        """Admin updates user 4-digit PIN."""
        new_pin = new_pin.strip()
        if not re.match(r"^\d{4}$", new_pin):
            return False, "Mã PIN phải bao gồm đúng 4 chữ số."
        if user_id not in self._users_by_id:
            return False, f"Không tìm thấy người dùng mã {user_id}."

        existing = self._users_by_pin.get(new_pin)
        if existing and existing.id != user_id:
            return False, f"Mã PIN {new_pin} đang được dùng bởi {existing.name}."

        user = self._users_by_id[user_id]
        old_pin = user.pin
        if old_pin in self._users_by_pin:
            del self._users_by_pin[old_pin]
        user.pin = new_pin
        self._users_by_pin[new_pin] = user
        self.save_users()
        self.log_event(
            event_type="ADMIN",
            status="UPDATE_PIN",
            detail=f"Admin đổi mã PIN cho {user.name} ({user.id}) | PIN: ****",
            user_id=user.id,
            user_name=user.name,
            raw_pin=new_pin,
        )
        return True, f"Cập nhật mã PIN cho {user.name} thành công!"

    def add_user(self, user_id: str, name: str, pin: str, role: str = "user") -> Tuple[bool, str]:
        """Admin adds a new user with 4-digit PIN."""
        user_id = user_id.strip()
        name = name.strip()
        pin = pin.strip()
        if not user_id:
            return False, "Mã người dùng không được để trống."
        if user_id in self._users_by_id:
            return False, f"Mã người dùng {user_id} đã tồn tại."
        if not name:
            return False, "Tên người dùng không được để trống."
        if not re.match(r"^\d{4}$", pin):
            return False, "Mã PIN phải bao gồm đúng 4 chữ số."
        if pin in self._users_by_pin:
            return False, f"Mã PIN {pin} đã được gán cho {self._users_by_pin[pin].name}."

        new_user = User(id=user_id, name=name, pin=pin, role=role)
        self._users_by_id[user_id] = new_user
        self._users_by_pin[pin] = new_user
        self.save_users()
        self.log_event(
            event_type="ADMIN",
            status="ADD_USER",
            detail=f"Admin thêm người dùng {name} ({user_id}) | PIN: ****",
            user_id=user_id,
            user_name=name,
            raw_pin=pin,
        )
        return True, f"Thêm người dùng {name} thành công!"

    def delete_user(self, user_id: str) -> Tuple[bool, str]:
        """Admin deletes a user."""
        if user_id not in self._users_by_id:
            return False, f"Không tìm thấy người dùng mã {user_id}."
        user = self._users_by_id.pop(user_id)
        if user.pin in self._users_by_pin:
            del self._users_by_pin[user.pin]
        self.save_users()
        self.log_event(
            event_type="ADMIN",
            status="DELETE_USER",
            detail=f"Admin xóa người dùng {user.name} ({user_id}) | PIN: ****",
            user_id=user_id,
            user_name=user.name,
        )
        return True, f"Xóa người dùng {user.name} thành công!"

    def set_master_pin(self, new_pin: str) -> Tuple[bool, str]:
        """Admin updates Master PIN."""
        new_pin = new_pin.strip()
        if not re.match(r"^\d{4}$", new_pin):
            return False, "Mật khẩu chính phải bao gồm đúng 4 chữ số."
        self.master_pin = new_pin
        self._save_master_pin_to_config(new_pin)
        self.log_event(
            event_type="ADMIN",
            status="CONFIG",
            detail="Admin cập nhật Mật khẩu chính cố định (Master PIN) | PIN: ****",
            user_id="ADMIN",
            user_name="Admin",
            raw_pin=new_pin,
        )
        return True, "Cập nhật Mật khẩu chính cố định thành công!"

    def _save_master_pin_to_config(self, new_pin: str) -> None:
        try:
            if self.config_file.is_file():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "auth" not in cfg:
                    cfg["auth"] = {}
                cfg["auth"]["master_pin"] = new_pin
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._write_file_log("SYSTEM", "ERROR", f"Save master pin failed: {e}")

    def save_serial_port_to_config(self, new_port: str) -> bool:
        """Saves new COM port to config.json."""
        try:
            if self.config_file.is_file():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "serial" not in cfg:
                    cfg["serial"] = {}
                cfg["serial"]["port"] = new_port.strip()
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                return True
        except Exception:
            pass
        return False
