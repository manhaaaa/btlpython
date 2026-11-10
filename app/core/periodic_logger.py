"""
Periodic Status Logger Service.
Logs system and door status every 30 minutes into an Excel-compatible CSV file in btl/data.
"""
import csv
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Dict, Any

# Target folder: btl/data
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
LOG_FILE_PATH = DATA_DIR / "periodic_status_log.csv"


class PeriodicStatusLogger:
    """
    Background worker thread that periodically captures and logs
    door and serial connection status into an Excel-compatible file.
    """

    def __init__(
        self,
        status_provider: Callable[[], Dict[str, Any]],
        interval_seconds: int = 1800,  # 30 minutes = 1800 seconds
        log_file: Optional[Path] = None,
    ):
        self.status_provider = status_provider
        self.interval_seconds = interval_seconds
        self.log_file = log_file or LOG_FILE_PATH
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the background periodic logging worker."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="PeriodicStatusLoggerWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops the periodic logging worker."""
        self._running = False

    def log_snapshot(self, trigger_note: str = "Dinh ky 30 phut") -> bool:
        """
        Immediately writes a single status snapshot row to the log file.
        Returns True if successful, False otherwise.
        """
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            file_exists = self.log_file.is_file()

            headers = [
                "Thoi_Gian",
                "Trang_Thai_Cua",
                "Ket_Noi_Serial",
                "Cong_COM",
                "Tong_Luot_Mo_Cua",
                "Tong_Luot_That_Bai",
                "Ghi_Chu",
            ]

            data = {}
            if self.status_provider:
                data = self.status_provider() or {}

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now_str,
                data.get("door_state", "CLOSED"),
                data.get("serial_state", "DISCONNECTED"),
                data.get("port", "COM6"),
                data.get("total_success", 0),
                data.get("total_failed", 0),
                trigger_note,
            ]

            # Use utf-8-sig encoding so Excel opens Vietnamese characters cleanly
            with open(self.log_file, mode="a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow(row)
            return True
        except Exception as e:
            print(f"[PERIODIC_LOGGER] Loi ghi log trang thai: {e}", flush=True)
            return False

    def _run_loop(self) -> None:
        """Background loop executing every interval_seconds."""
        # Initial snapshot on startup
        self.log_snapshot(trigger_note="Khoi dong he thong")

        elapsed = 0.0
        step = 5.0  # Check running flag every 5 seconds
        while self._running:
            time.sleep(step)
            elapsed += step
            if elapsed >= self.interval_seconds:
                elapsed = 0.0
                self.log_snapshot(trigger_note="Dinh ky 30 phut")
