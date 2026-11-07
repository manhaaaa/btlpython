"""
Serial Communication Bridge Module
Handles serial communication with PIC16F877A via PySerial.
Implements:
- Configurable COM port & baudrate
- Auto-reconnect loop on port disconnection without crashing
- Input validation with regex ^\\d{4}$ after stripping \\r\\n
- Discards invalid/garbage data with warning log
- Lockout state machine: 3 consecutive fails trigger temporary lockout
- Responds '1' (granted), '0' (denied), 'L' (locked out)
- Thread-safe background execution and mockable interface
"""

import sys
import os
import time
import re
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any

# Prevent bytecode generation
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

try:
    import serial
except ImportError:
    serial = None

try:
    from .auth_service import AuthService, User
except (ImportError, ValueError):
    from auth_service import AuthService, User


class SerialBridge:
    """
    Serial Bridge managing bidirectional communication between PIC16F877A and Python backend.
    """

    def __init__(
        self,
        port: str = "COM2",
        baudrate: int = 9600,
        timeout: float = 1.0,
        lockout_duration: float = 30.0,
        auth_service: Optional[AuthService] = None,
        auth_callback: Optional[Callable[[str], Optional[User]]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        serial_instance: Optional[Any] = None,
        config_file: Optional[str | Path] = None,
    ):
        # Optional load from config
        self._load_config(config_file, port, baudrate, lockout_duration)

        self.timeout = timeout
        self.auth_service = auth_service or AuthService()
        self.auth_callback = auth_callback
        self.on_state_change = on_state_change
        self.on_log = on_log

        # State tracking
        self.consecutive_fails: int = 0
        self.lockout_until: float = 0.0
        self.state: str = "IDLE"  # IDLE, LOCKED, CONNECTED, DISCONNECTED

        # Serial & Threading
        self._serial: Optional[Any] = serial_instance
        self._is_injected_serial: bool = serial_instance is not None
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._connected: bool = False

        # Metrics
        self.metrics = {
            "total_received": 0,
            "access_granted": 0,
            "access_denied": 0,
            "lockout_triggers": 0,
            "invalid_payloads": 0,
        }

    def _load_config(
        self,
        config_file: Optional[str | Path],
        default_port: str,
        default_baud: int,
        default_lockout: float,
    ) -> None:
        self.port = default_port
        self.baudrate = default_baud
        self.lockout_duration = default_lockout

        cfg_path = (
            Path(config_file)
            if config_file
            else (Path(__file__).resolve().parent / "config.json")
        )
        if cfg_path.is_file():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                serial_cfg = cfg.get("serial", {})
                self.port = serial_cfg.get("port", self.port)
                self.baudrate = int(serial_cfg.get("baudrate", self.baudrate))
                self.lockout_duration = float(
                    serial_cfg.get("lockout_duration", self.lockout_duration)
                )
            except Exception:
                pass

    def is_locked(self) -> bool:
        """Checks if system is currently locked out."""
        return time.monotonic() < self.lockout_until

    def remaining_lockout(self) -> float:
        """Returns remaining lockout seconds, or 0.0 if not locked."""
        rem = self.lockout_until - time.monotonic()
        return max(0.0, rem)

    def is_connected(self) -> bool:
        """Checks if serial connection is active."""
        if self._serial is not None:
            return getattr(self._serial, "is_open", True)
        return self._connected

    def _log(self, message: str) -> None:
        if self.on_log:
            try:
                self.on_log(message)
            except Exception:
                pass

    def _set_state(self, new_state: str) -> None:
        if self.state != new_state:
            self.state = new_state
            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception:
                    pass

    def process_line(self, line: str) -> Optional[str]:
        """
        Synchronously processes a received raw UART string.
        - Strips \\r\\n.
        - Validates with regex ^\\d{4}$.
        - Discards invalid/garbage input without response.
        - Evaluates lockout state: returns 'L' if locked.
        - Authenticates PIN: returns '1' on match, '0' on mismatch, 'L' on 3rd consecutive fail.
        """
        with self._lock:
            # Strip \r and \n
            sanitized = line.strip("\r\n")

            # Validate 4 digits
            if not re.match(r"^\d{4}$", sanitized):
                self.metrics["invalid_payloads"] += 1
                self._log(
                    f"Warning: Discarded invalid UART payload: {repr(sanitized)} (expected 4 digits)"
                )
                return None

            self.metrics["total_received"] += 1
            pin = sanitized

            # 1. Check if already locked out
            if self.is_locked():
                self.metrics["lockout_triggers"] += 1
                self._set_state("LOCKED")
                self._log(
                    f"Warning: Attempt during lockout ({self.remaining_lockout():.1f}s remaining). Response: 'L'"
                )
                return "L"

            # 2. Authenticate PIN (Master PIN or User PIN)
            user = None
            if self.auth_callback:
                user = self.auth_callback(pin)
            elif self.auth_service:
                user = self.auth_service.authenticate(pin)

            if user is not None:
                # Access Granted
                self.consecutive_fails = 0
                self.metrics["access_granted"] += 1
                self._set_state("ACCESS_GRANTED")
                self._log(f"Success: Valid PIN for user '{user.name}'. Response: '1'")
                return "1"
            else:
                # Access Denied
                self.consecutive_fails += 1
                self.metrics["access_denied"] += 1

                if self.consecutive_fails >= 3:
                    # Trigger Lockout
                    self.lockout_until = time.monotonic() + self.lockout_duration
                    self.consecutive_fails = 0
                    self.metrics["lockout_triggers"] += 1
                    self._set_state("LOCKED")
                    if self.auth_service:
                        self.auth_service.log_lockout(self.lockout_duration)
                    self._log(
                        f"Alert: 3 consecutive failed attempts! Lockout for {self.lockout_duration:.1f}s. Response: 'L'"
                    )
                    return "L"
                else:
                    self._set_state("ACCESS_DENIED")
                    self._log(
                        f"Notice: Invalid PIN (attempt {self.consecutive_fails}/3). Response: '0'"
                    )
                    return "0"

    def send_response(self, char: str) -> bool:
        """Sends a single ASCII character response back to the PIC."""
        if not self._serial:
            return False
        try:
            payload = char.encode("ascii")
            self._serial.write(payload)
            if hasattr(self._serial, "flush"):
                self._serial.flush()
            return True
        except Exception as e:
            self._log(f"Error sending serial response '{char}': {e}")
            return False

    def start(self) -> None:
        """Starts the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="SerialBridgeThread", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Gracefully stops the serial bridge and closes port."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_serial()
        self._set_state("DISCONNECTED")

    def _close_serial(self) -> None:
        """Closes serial connection if managed internally."""
        if not self._is_injected_serial and self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            self._connected = False

    def _attempt_connect(self) -> bool:
        """Attempts to open the configured serial COM port."""
        if self._is_injected_serial and self._serial is not None:
            self._connected = True
            return True

        if serial is None:
            self._log("Error: pyserial library not available")
            return False

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            self._connected = True
            self._set_state("CONNECTED")
            self._log(f"Connected to serial port {self.port} at {self.baudrate} baud.")
            return True
        except (serial.SerialException, OSError) as e:
            self._connected = False
            self._serial = None
            self._set_state("DISCONNECTED")
            return False

    def _run_loop(self) -> None:
        """Main background reading and processing loop with auto-reconnect."""
        reconnect_interval = 2.0
        last_reconnect_attempt = 0.0

        while self._running:
            # 1. Connection check & Auto-reconnect
            if not self.is_connected():
                now = time.monotonic()
                if now - last_reconnect_attempt >= reconnect_interval:
                    last_reconnect_attempt = now
                    connected = self._attempt_connect()
                    if not connected:
                        time.sleep(0.5)
                        continue
                else:
                    time.sleep(0.2)
                    continue

            # 2. Read from serial
            try:
                if self._serial is None:
                    continue

                # Read line terminated by \n or until timeout
                raw_bytes = self._serial.readline()
                if not raw_bytes:
                    continue

                line = raw_bytes.decode("ascii", errors="replace")
                response = self.process_line(line)
                if response:
                    self.send_response(response)

            except (serial.SerialException, OSError) as e:
                self._log(f"Serial I/O error on port {self.port}: {e}. Retrying connection...")
                self._close_serial()
                self._set_state("DISCONNECTED")
                time.sleep(0.5)
            except Exception as e:
                self._log(f"Unexpected error in serial bridge loop: {e}")
                time.sleep(0.2)
