"""
Cầu nối giao tiếp nối tiếp
Xử lý giao tiếp nối tiếp với PIC16F877A thông qua PySerial.
Các chức năng:
- Cấu hình cổng COM và tốc độ truyền
- Tự động kết nối lại khi mất kết nối cổng mà không làm chương trình bị dừng
- Kiểm tra đầu vào bằng biểu thức chính quy ^\\d{4}$ sau khi loại bỏ \\r\\n
- Loại bỏ dữ liệu không hợp lệ/rác và ghi nhật ký cảnh báo
- Máy trạng thái khóa: khóa tạm thời sau 3 lần nhập sai liên tiếp
- Phản hồi '1' (cho phép), '0' (từ chối), 'L' (đang bị khóa)
- Chạy nền an toàn với luồng và hỗ trợ giao diện giả lập để kiểm thử
- Phản hồi PIC NGAY LẬP TỨC; các hàm gọi lại giao diện/trạng thái chạy trên luồng riêng
  để việc cập nhật giao diện chậm không làm trì hoãn phản hồi PIC (thời gian chờ PIC = 5 giây)
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
    import serial.tools.list_ports
except ImportError:
    serial = None

try:
    from .auth_service import AuthService, User
except (ImportError, ValueError):
    from auth_service import AuthService, User


def list_available_ports() -> list[str]:
    """
    Tìm các cổng COM khả dụng từ hai nguồn:
    1. Liệt kê cổng theo cách chuẩn của PySerial (serial.tools.list_ports.comports())
    2. Tra cứu Windows Registry HKEY_LOCAL_MACHINE\\HARDWARE\\DEVICEMAP\\SERIALCOMM
       (phát hiện các cổng ảo như cặp com0com COM1, COM2)
    3. Thử trực tiếp các cổng tiềm năng (COM1 đến COM9) bằng serial.Serial
    Trả về danh sách tên cổng đã sắp xếp (ví dụ: ['COM1', 'COM2', 'COM5', 'COM6']).
    """
    found_ports = set()

    # 1. Liệt kê cổng bằng PySerial
    if serial is not None and hasattr(serial, "tools") and hasattr(serial.tools, "list_ports"):
        try:
            for port_info in serial.tools.list_ports.comports():
                if port_info.device:
                    found_ports.add(port_info.device.upper())
        except Exception:
            pass

    # 2. Tra cứu Windows Registry để tìm cổng ẩn/ảo (com0com)
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                for i in range(1024):
                    try:
                        _, val, _ = winreg.EnumValue(key, i)
                        if val and isinstance(val, str) and val.upper().startswith("COM"):
                            found_ports.add(val.upper())
                    except OSError:
                        break
        except Exception:
            pass

    # 3. Thử trực tiếp các cổng tiềm năng (COM1 đến COM9) nếu chưa tìm thấy cổng nào
    if not found_ports and serial is not None:
        for i in range(1, 10):
            p = f"COM{i}"
            try:
                s = serial.Serial(p)
                s.close()
                found_ports.add(p)
            except (serial.SerialException, OSError) as e:
                err_str = str(e).lower()
                if "access is denied" in err_str or "permission" in err_str:
                    found_ports.add(p)
            except Exception:
                pass

    # Sắp xếp tự nhiên theo số thứ tự cổng COM
    def _sort_key(port_name: str) -> int:
        m = re.search(r"\d+", port_name)
        return int(m.group(0)) if m else 999

    return sorted(list(found_ports), key=_sort_key)


class SerialBridge:
    """Cầu nối nối tiếp quản lý giao tiếp hai chiều giữa PIC16F877A và Python."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: Optional[int] = None,
        timeout: Optional[float] = None,
        lockout_duration: Optional[float] = None,
        auth_service: Optional[AuthService] = None,
        auth_callback: Optional[Callable[[str], Optional[User]]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        serial_instance: Optional[Any] = None,
        config_file: Optional[str | Path] = None,
        master_pin: Optional[str] = None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.lockout_duration = lockout_duration

        # Tùy chọn tải cấu hình; các đối số truyền trực tiếp được ưu tiên
        self._load_config(config_file)

        # Dùng giá trị mặc định nếu đối số khởi tạo và config.json đều không cung cấp
        if self.port is None:
            self.port = "COM6"
        if self.baudrate is None:
            self.baudrate = 9600
        if self.timeout is None:
            self.timeout = 0.1
        if self.lockout_duration is None:
            self.lockout_duration = 30.0

        self.auth_service = auth_service or AuthService()
        self.auth_callback = auth_callback
        self.on_state_change = on_state_change
        self.on_log = on_log

        # Cấu hình mật khẩu chủ (R3, AC7)
        self.master_pin = master_pin
        if self.master_pin is None and self.auth_service is not None:
            self.master_pin = getattr(self.auth_service, "master_pin", "1234")
        if self.master_pin is None:
            self.master_pin = "1234"

        # Theo dõi trạng thái
        self.consecutive_fails: int = 0
        self.lockout_until: float = 0.0
        self.state: str = "IDLE"  # IDLE: chờ, LOCKED: bị khóa, CONNECTED: đã kết nối, DISCONNECTED: mất kết nối

        # Cổng nối tiếp và luồng
        self._serial: Optional[Any] = serial_instance
        self._is_injected_serial: bool = serial_instance is not None
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._connected: bool = False
        self._pic_alive: bool = False
        self._rx_buf: str = ""
        self.debug_timing: bool = os.environ.get("DOOR_DEBUG", "0") == "1"

        # Thống kê
        self.metrics = {
            "total_received": 0,
            "access_granted": 0,
            "access_denied": 0,
            "lockout_triggers": 0,
            "invalid_payloads": 0,
        }

    def _load_config(
        self,
        config_file: Optional[str | Path] = None,
    ) -> None:
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
                if self.port is None and "port" in serial_cfg:
                    self.port = str(serial_cfg["port"])
                if self.baudrate is None and "baudrate" in serial_cfg:
                    self.baudrate = int(serial_cfg["baudrate"])
                if self.timeout is None and "timeout" in serial_cfg:
                    self.timeout = float(serial_cfg["timeout"])
                if self.lockout_duration is None and "lockout_duration" in serial_cfg:
                    self.lockout_duration = float(serial_cfg["lockout_duration"])
            except Exception:
                pass

    def is_locked(self) -> bool:
        """Kiểm tra hệ thống hiện có đang bị khóa hay không."""
        return time.monotonic() < self.lockout_until

    def remaining_lockout(self) -> float:
        """Trả về số giây còn bị khóa, hoặc 0.0 nếu không bị khóa."""
        rem = self.lockout_until - time.monotonic()
        return max(0.0, rem)

    def is_connected(self) -> bool:
        """Kiểm tra kết nối nối tiếp có đang hoạt động hay không."""
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
        """Cập nhật trạng thái; thông báo cho bộ lắng nghe trên một luồng nền riêng.

        Hàm gọi lại (cập nhật giao diện Flet, làm mới nhật ký...) không được chạy trên
        luồng nối tiếp, nếu không sẽ làm chậm phản hồi '1'/'0'/'L' gửi đến PIC.
        """
        if self.state != new_state:
            self.state = new_state
            if self.on_state_change:
                threading.Thread(
                    target=self._run_state_cb,
                    args=(new_state,),
                    name="SerialStateCallback",
                    daemon=True,
                ).start()

    def _run_state_cb(self, state: str) -> None:
        try:
            self.on_state_change(state)
        except Exception:
            pass

    def process_line(self, line: str) -> Optional[str]:
        """
        Xử lý đồng bộ chuỗi UART thô nhận được.
        - Loại bỏ \\r\\n.
        - Kiểm tra bằng biểu thức chính quy ^\\d{4}$.
        - Loại bỏ dữ liệu không hợp lệ/rác mà không phản hồi.
        - Kiểm tra trạng thái khóa: trả về 'L' nếu đang bị khóa.
        - Xác thực mã PIN: trả về '1' nếu khớp, '0' nếu không khớp,
          'L' nếu đây là lần sai liên tiếp thứ ba.
        """
        with self._lock:
            # Loại bỏ byte null và khoảng trắng ở đầu/cuối (nhiễu khởi động từ Proteus COMPIM)
            sanitized = line.strip("\x00\r\n\t ")

            # Yêu cầu chính xác 4 chữ số: loại bỏ byte null xen giữa, dữ liệu chèn vào hoặc sai độ dài
            if not re.match(r"^\d{4}$", sanitized):
                self.metrics["invalid_payloads"] += 1
                self._log(
                    f"Cảnh báo: Đã loại bỏ dữ liệu UART không hợp lệ: {repr(line)} (cần đúng 4 chữ số)"
                )
                return None

            pin = sanitized
            self._pic_alive = True
            self.metrics["total_received"] += 1

            # 1. Ưu tiên bỏ qua bằng mật khẩu chủ (R3 và AC7):
            # Mật khẩu chủ LUÔN mở khóa cửa trong mọi điều kiện (kể cả khi đang bị khóa),
            # đặt lại thời gian khóa và bộ đếm lần sai, rồi lập tức trả về '1'.
            master_pin = self.master_pin or (
                getattr(self.auth_service, "master_pin", "1234")
                if self.auth_service
                else "1234"
            )
            if pin == master_pin:
                self.lockout_until = 0.0
                self.consecutive_fails = 0
                self.metrics["access_granted"] += 1
                self._set_state("ACCESS_GRANTED")
                if self.auth_service:
                    self.auth_service.authenticate(pin)
                self._log("Thành công: Đã nhập khóa chủ. Bỏ qua trạng thái khóa. Phản hồi: '1'")
                return "1"

            # 2. Kiểm tra hiện có bị khóa hay không (đối với mã PIN người dùng thông thường)
            if self.is_locked():
                self.metrics["lockout_triggers"] += 1
                self._set_state("LOCKED")
                self._log(
                    f"Cảnh báo: Có lần thử trong thời gian khóa (còn {self.remaining_lockout():.1f} giây). Phản hồi: 'L'"
                )
                return "L"

            # 3. Xác thực mã PIN người dùng thông thường
            user = None
            if self.auth_callback:
                user = self.auth_callback(pin)
            elif self.auth_service:
                user = self.auth_service.authenticate(pin)

            if user is not None:
                # Cho phép truy cập
                self.consecutive_fails = 0
                self.metrics["access_granted"] += 1
                self._set_state("ACCESS_GRANTED")
                self._log(f"Thành công: Mã PIN hợp lệ của người dùng '{user.name}'. Phản hồi: '1'")
                return "1"
            else:
                # Từ chối truy cập
                self.consecutive_fails += 1
                self.metrics["access_denied"] += 1

                if self.consecutive_fails >= 3:
                    # Kích hoạt khóa
                    self.lockout_until = time.monotonic() + self.lockout_duration
                    self.consecutive_fails = 0
                    self.metrics["lockout_triggers"] += 1
                    self._set_state("LOCKED")
                    if self.auth_service:
                        self.auth_service.log_lockout(self.lockout_duration)
                    self._log(
                        f"Cảnh báo: Đã nhập sai 3 lần liên tiếp! Khóa trong {self.lockout_duration:.1f} giây. Phản hồi: 'L'"
                    )
                    return "L"
                else:
                    self._set_state("ACCESS_DENIED")
                    self._log(
                        f"Thông báo: Mã PIN không hợp lệ (lần thử {self.consecutive_fails}/3). Phản hồi: '0'"
                    )
                    return "0"

    def send_response(self, char: str) -> bool:
        """Gửi một ký tự ASCII phản hồi về PIC."""
        if not self._serial:
            return False
        try:
            payload = char.encode("ascii")
            self._serial.write(payload)
            if hasattr(self._serial, "flush"):
                try:
                    self._serial.flush()
                except Exception:
                    pass
            return True
        except Exception as e:
            self._log(f"Lỗi khi gửi phản hồi nối tiếp '{char}': {e}")
            return False

    def start(self) -> None:
        """Khởi chạy luồng xử lý nền."""
        if self._running:
            return
        self._attempt_connect()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="SerialBridgeThread", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Dừng cầu nối nối tiếp an toàn và đóng cổng."""
        self._running = False
        self._close_serial()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._set_state("DISCONNECTED")

    def _close_serial(self) -> None:
        """Đóng kết nối nối tiếp nếu kết nối do chương trình quản lý."""
        if not self._is_injected_serial and self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            self._connected = False
            self._pic_alive = False
            self._rx_buf = ""

    def _attempt_connect(self) -> bool:
        """Thử mở cổng COM nối tiếp đã cấu hình."""
        if self._is_injected_serial and self._serial is not None:
            self._connected = True
            return True

        if serial is None:
            self._log("Lỗi: Không tìm thấy thư viện pyserial")
            return False

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout or 0.1,
            )
            # Xóa bộ đệm khi kết nối để tránh đọc nhiễu khởi động cũ từ Proteus COMPIM
            try:
                if hasattr(self._serial, "reset_input_buffer"):
                    self._serial.reset_input_buffer()
                if hasattr(self._serial, "reset_output_buffer"):
                    self._serial.reset_output_buffer()
            except Exception:
                pass
            self._connected = True
            self._set_state("PORT_OPEN")
            self._log(f"Đã kết nối cổng nối tiếp {self.port} ở tốc độ {self.baudrate} baud. Đang chờ PIC...")
            if self.debug_timing:
                print(f"[BRIDGE] Đã mở {self.port} @ {self.baudrate}. Đang chờ mã PIN / bắt tay...", flush=True)
            self.send_response("?\n")
            return True
        except (serial.SerialException, OSError) as e:
            self._connected = False
            self._pic_alive = False
            self._serial = None
            self._set_state("DISCONNECTED")
            if self.debug_timing:
                print(f"[BRIDGE] Không thể mở {self.port}: {e}", flush=True)
            return False

    def _drain_buffer(self) -> None:
        """Phân tích các dòng hoàn chỉnh kết thúc bằng \\n, xử lý mã bắt tay/ping và chuyển mã PIN đi xác thực."""
        while "\n" in self._rx_buf:
            line, self._rx_buf = self._rx_buf.split("\n", 1)
            sanitized = line.strip("\x00\r\t ")

            # Mã bắt tay/nhịp sống từ PIC
            if sanitized in ("READY", "PIC_READY", "PONG", "ALIVE", "HELLO", "!"):
                self._pic_alive = True
                self._set_state("CONNECTED")
                self._log(f"Đã nhận mã bắt tay từ PIC: '{sanitized}' -> Đường truyền đã xác thực.")
                if self.debug_timing:
                    print(f"[BRIDGE] Bắt tay PIC thành công: {sanitized!r}", flush=True)
                continue
            elif sanitized in ("PING", "?"):
                self._pic_alive = True
                self.send_response("!\n")
                continue
            elif sanitized == "CLOSED":
                # PIC thông báo cửa đã đóng bằng nút vật lý (RA0)
                self._pic_alive = True
                self._set_state("DOOR_CLOSED")
                self._log("Cửa đã được đóng bằng nút nhấn trên PIC.")
                if self.debug_timing:
                    print("[BRIDGE] Cửa đã ĐÓNG bằng nút nhấn", flush=True)
                continue

            # Xử lý khung dữ liệu (xác thực mã PIN hoặc ghi nhận dữ liệu không hợp lệ)
            t0 = time.monotonic()
            response = self.process_line(line)
            if response:
                ok = self.send_response(response)
                if self.debug_timing:
                    dt = (time.monotonic() - t0) * 1000
                    print(
                        f"[BRIDGE] rx={line!r} tx={response!r} ok={ok} dt={dt:.0f}ms",
                        flush=True,
                    )

        # Giới hạn kích thước bộ đệm để tránh rò rỉ bộ nhớ do dữ liệu nhiễu không kết thúc
        if len(self._rx_buf) > 1024:
            self._rx_buf = self._rx_buf[-64:]

    def _run_loop(self) -> None:
        """Vòng lặp đọc và xử lý nền chính, tự động kết nối lại và gửi ping duy trì định kỳ."""
        reconnect_interval = 2.0
        last_reconnect_attempt = 0.0
        last_ping_time = time.monotonic()

        while self._running:
            # 1. Kiểm tra kết nối và tự động kết nối lại
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

            # 2. Gửi ping duy trì định kỳ nếu đường truyền PIC chưa được xác thực (mỗi 3 giây)
            now = time.monotonic()
            if not self._is_injected_serial and not self._pic_alive and (now - last_ping_time >= 3.0):
                last_ping_time = now
                self.send_response("?\n")
                if self.debug_timing:
                    print(f"[BRIDGE] Đã gửi ping duy trì '?' đến {self.port}", flush=True)

            # 3. Đọc dữ liệu từ cổng nối tiếp
            try:
                if self._serial is None:
                    continue

                # Đọc byte thô; xử lý ngay khi nhận đủ 4 chữ số
                # (không phụ thuộc vào '\\n' hay thời gian chờ đọc)
                waiting = getattr(self._serial, "in_waiting", 0) or 1
                chunk = self._serial.read(waiting)
                if not chunk:
                    continue

                if self.debug_timing:
                    print(f"[BRIDGE] Byte nhận thô: {chunk!r}", flush=True)
                self._rx_buf += chunk.decode("ascii", errors="replace")
                self._drain_buffer()

            except (serial.SerialException, OSError) as e:
                self._log(f"Lỗi vào/ra nối tiếp tại cổng {self.port}: {e}. Đang thử kết nối lại...")
                self._close_serial()
                self._set_state("DISCONNECTED")
                time.sleep(0.5)
            except Exception as e:
                self._log(f"Lỗi không mong đợi trong vòng lặp cầu nối nối tiếp: {e}")
                time.sleep(0.2)
