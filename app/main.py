"""
Smart PIN Door Lock System - Multiplatform Flet Application
Unified single codebase supporting Windows Desktop and Android.

Features:
- Real-time door status indicator: CLOSED, OPEN (unlocked 3s), LOCKED (alarm).
- Serial connection status: CONNECTED, DISCONNECTED, RECONNECTING (Desktop only).
- Live access log table: Timestamp, Event Type, Status (SUCCESS, FAILED, LOCKOUT), Detail (PIN masked).
- User management view: Configured user profiles with masked PINs.
- Interactive controls: Open/Reconnect COM, Refresh logs, Clear log display.
- Runtime platform separation:
  - On Desktop: Initializes SerialBridge and AuthService with auto-reconnect resilience.
  - On Android: Runs in Demo/Monitoring mode using demo_data.py; serial controls are hidden.
  - CRITICAL CONSTRAINT: Under Android, NEVER import pyserial, auth_service, or data/.
"""

import sys
import os
import time
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable

# Enforce strict bytecode prevention
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import flet as ft

# Relative/Absolute import fallback for demo_data
try:
    from app.demo_data import (
        get_demo_users,
        get_demo_logs,
        generate_simulated_event,
        clear_demo_logs,
    )
except (ImportError, ModuleNotFoundError):
    from demo_data import (
        get_demo_users,
        get_demo_logs,
        generate_simulated_event,
        clear_demo_logs,
    )

# Desktop-only modules are NOT imported at top level to ensure Android compatibility
_SerialBridgeClass = None
_AuthServiceClass = None


def is_android_platform(page: Optional[ft.Page] = None) -> bool:
    """
    Detects if the application is running in Android or Demo/Monitoring mode.
    Checks environment variables and Flet PagePlatform.
    """
    forced = os.environ.get("FORCE_PLATFORM", "").strip().lower()
    if forced in ("android", "demo"):
        return True
    if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_BOOTLOGO"):
        return True
    if page is not None:
        plat = getattr(page, "platform", None)
        if plat in (ft.PagePlatform.ANDROID, ft.PagePlatform.ANDROID_TV):
            return True
    return False


def load_desktop_modules():
    """
    Dynamically loads SerialBridge and AuthService only when executing on Desktop.
    Guarantees that on Android, pyserial and auth_service are never imported.
    """
    global _SerialBridgeClass, _AuthServiceClass
    if _SerialBridgeClass is None or _AuthServiceClass is None:
        try:
            from app.auth_service import AuthService
            from app.serial_bridge import SerialBridge
            _AuthServiceClass = AuthService
            _SerialBridgeClass = SerialBridge
        except (ImportError, ModuleNotFoundError):
            from auth_service import AuthService
            from serial_bridge import SerialBridge
            _AuthServiceClass = AuthService
            _SerialBridgeClass = SerialBridge
    return _SerialBridgeClass, _AuthServiceClass


class DoorLockApp:
    """
    Controller and UI builder for the Smart Door Lock Flet Application.
    """

    def __init__(
        self,
        page: ft.Page,
        is_android: Optional[bool] = None,
        serial_instance: Optional[Any] = None,
    ):
        self.page = page
        self.is_android = is_android if is_android is not None else is_android_platform(page)
        self.injected_serial = serial_instance

        # State tracking
        self.door_state: str = "CLOSED"  # CLOSED, OPEN, LOCKED
        self.serial_state: str = "DISCONNECTED"  # CONNECTED, DISCONNECTED, RECONNECTING
        self.current_view_index: int = 0

        # Backend handles (Desktop only)
        self.auth_service = None
        self.serial_bridge = None
        self._door_timer: Optional[threading.Timer] = None

        # Initialize Desktop Backend if applicable
        if not self.is_android:
            self._init_desktop_backend()

    def _init_desktop_backend(self) -> None:
        """Initializes AuthService and SerialBridge for Desktop operation."""
        try:
            serial_cls, auth_cls = load_desktop_modules()
            self.auth_service = auth_cls()
            self.serial_bridge = serial_cls(
                port="COM2",
                baudrate=9600,
                lockout_duration=30.0,
                auth_service=self.auth_service,
                on_state_change=self.handle_serial_state_change,
                on_log=self.handle_serial_log,
                serial_instance=self.injected_serial,
            )
            self.serial_state = "CONNECTED" if self.serial_bridge.is_connected() else "DISCONNECTED"
        except Exception as e:
            self.serial_state = "DISCONNECTED"

    def handle_serial_state_change(self, state: str) -> None:
        """Callback invoked by SerialBridge when connection or auth state transitions."""
        if state == "ACCESS_GRANTED":
            self.set_door_state("OPEN", "Mở khóa thành công (Relay kích hoạt 3s)")
        elif state == "LOCKED":
            self.set_door_state("LOCKED", "Cảnh báo: Khóa tạm sau 3 lần nhập sai")
        elif state == "ACCESS_DENIED":
            self.set_door_state("CLOSED", "Từ chối truy cập: Mã PIN không đúng")
        elif state in ("CONNECTED", "DISCONNECTED", "RECONNECTING"):
            self.set_serial_state(state)

        # Refresh log list whenever an authentication or alarm event occurs
        self.refresh_logs()

    def handle_serial_log(self, message: str) -> None:
        """Handles serial log messages."""
        pass

    def set_door_state(self, new_state: str, detail: str = "") -> None:
        """Updates the door state indicator and handles auto-lock timer."""
        self.door_state = new_state

        if self._door_timer and self._door_timer.is_alive():
            self._door_timer.cancel()

        if new_state == "OPEN":
            # Auto-lock after 3 seconds (matching hardware relay pulse)
            self._door_timer = threading.Timer(3.0, self._auto_close_door)
            self._door_timer.daemon = True
            self._door_timer.start()

        self._update_door_ui(detail)

    def _auto_close_door(self) -> None:
        """Timer callback returning door to CLOSED state."""
        self.door_state = "CLOSED"
        self._update_door_ui("Cửa đã đóng lại bình thường")

    def set_serial_state(self, new_state: str) -> None:
        """Updates the serial connection state indicator."""
        self.serial_state = new_state
        self._update_serial_ui()

    def build_ui(self) -> None:
        """Builds and mounts the complete Flet user interface."""
        self.page.title = "Smart PIN Door Lock System"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 16

        # App Bar
        subtitle_text = (
            "📱 Android - Chế độ Giám sát / Demo"
            if self.is_android
            else "💻 Windows Desktop - Kết nối Cổng Serial Thực tế"
        )
        self.page.appbar = ft.AppBar(
            title=ft.Column(
                [
                    ft.Text("HỆ THỐNG KHÓA CỬA THÔNG MINH PIN", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitle_text, size=12, color=ft.Colors.WHITE70),
                ],
                spacing=2,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            center_title=False,
        )

        # Status Cards
        self.door_icon = ft.Icon(ft.Icons.LOCK, size=48, color=ft.Colors.AMBER)
        self.door_label = ft.Text("CỬA ĐANG ĐÓNG", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER)
        self.door_desc = ft.Text("Chờ tín hiệu từ PIC16F877A U1", size=12, color=ft.Colors.WHITE60)

        self.door_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        self.door_icon,
                        ft.Column(
                            [
                                ft.Text("TRẠNG THÁI CỬA", size=11, color=ft.Colors.WHITE54, weight=ft.FontWeight.BOLD),
                                self.door_label,
                                self.door_desc,
                            ],
                            spacing=3,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=16,
            ),
            expand=True,
        )

        # Serial / Platform Card
        if not self.is_android:
            self.serial_icon = ft.Icon(ft.Icons.CABLE, size=48, color=ft.Colors.RED)
            self.serial_label = ft.Text("MẤT KẾT NỐI", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED)
            self.serial_desc = ft.Text("Cổng COM: COM2 | Baud: 9600 8N1", size=12, color=ft.Colors.WHITE60)
            self.serial_card = ft.Card(
                content=ft.Container(
                    content=ft.Row(
                        [
                            self.serial_icon,
                            ft.Column(
                                [
                                    ft.Text("KẾT NỐI SERIAL COMPIM", size=11, color=ft.Colors.WHITE54, weight=ft.FontWeight.BOLD),
                                    self.serial_label,
                                    self.serial_desc,
                                ],
                                spacing=3,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=16,
                ),
                expand=True,
            )
        else:
            self.serial_icon = ft.Icon(ft.Icons.PHONE_ANDROID, size=48, color=ft.Colors.CYAN)
            self.serial_label = ft.Text("CHẾ ĐỘ DEMO", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN)
            self.serial_desc = ft.Text("Độc lập phần cứng | Không yêu cầu PySerial", size=12, color=ft.Colors.WHITE60)
            self.serial_card = ft.Card(
                content=ft.Container(
                    content=ft.Row(
                        [
                            self.serial_icon,
                            ft.Column(
                                [
                                    ft.Text("NỀN TẢNG ANDROID", size=11, color=ft.Colors.WHITE54, weight=ft.FontWeight.BOLD),
                                    self.serial_label,
                                    self.serial_desc,
                                ],
                                spacing=3,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=16,
                ),
                expand=True,
            )

        cards_row = ft.Row([self.door_card, self.serial_card], spacing=16)

        # Interactive Controls Bar
        controls_items = []
        if not self.is_android:
            self.port_input = ft.TextField(
                label="Cổng COM",
                value="COM2",
                width=110,
                dense=True,
            )
            self.connect_btn = ft.FilledButton(
                "Kết nối lại",
                icon=ft.Icons.SYNC,
                on_click=self._on_reconnect_click,
            )
            controls_items.extend([self.port_input, self.connect_btn])
        else:
            # Android Simulation Controls
            btn_sim_success = ft.FilledButton(
                "Mô phỏng: Đúng PIN",
                icon=ft.Icons.CHECK_CIRCLE,
                bgcolor=ft.Colors.GREEN_700,
                on_click=lambda _: self._on_sim_event("SUCCESS"),
            )
            btn_sim_fail = ft.FilledButton(
                "Mô phỏng: Sai PIN",
                icon=ft.Icons.CANCEL,
                bgcolor=ft.Colors.ORANGE_800,
                on_click=lambda _: self._on_sim_event("FAILED"),
            )
            btn_sim_lock = ft.FilledButton(
                "Mô phỏng: Khóa tạm",
                icon=ft.Icons.WARNING,
                bgcolor=ft.Colors.RED_800,
                on_click=lambda _: self._on_sim_event("LOCKOUT"),
            )
            controls_items.extend([btn_sim_success, btn_sim_fail, btn_sim_lock])

        btn_refresh = ft.OutlinedButton(
            "Làm mới",
            icon=ft.Icons.REFRESH,
            on_click=lambda _: self.refresh_all(),
        )
        btn_clear = ft.OutlinedButton(
            "Xóa hiển thị",
            icon=ft.Icons.CLEAR_ALL,
            on_click=lambda _: self.clear_logs_display(),
        )
        controls_items.extend([btn_refresh, btn_clear])

        controls_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    controls_items,
                    alignment=ft.MainAxisAlignment.START,
                    wrap=True,
                    spacing=10,
                ),
                padding=12,
            )
        )

        # Main Log Table
        self.log_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Thời gian", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Sự kiện", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Trạng thái", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Chi tiết (Mã PIN bảo mật ****)", weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            show_bottom_border=True,
        )

        self.logs_container = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("NHẬT KÝ RA VÀO THỜI GIAN THỰC", size=15, weight=ft.FontWeight.BOLD),
                            ft.Text("(Dữ liệu được bảo vệ an toàn - PIN luôn che dạng ****)", size=12, color=ft.Colors.WHITE54),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(),
                    ft.ListView(
                        controls=[self.log_table],
                        expand=True,
                        spacing=0,
                    ),
                ],
                expand=True,
            ),
            expand=True,
            padding=8,
        )

        # User Management Table
        self.users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Mã Người Dùng", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Họ và Tên", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Vai Trò", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Mã PIN Bảo Mật", weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            show_bottom_border=True,
        )

        self.users_container = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("DANH SÁCH NGƯỜI DÙNG ĐÃ ĐĂNG KÝ", size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "(Nguồn: Cấu hình an toàn / Không chứa PIN thô)",
                                size=12,
                                color=ft.Colors.WHITE54,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(),
                    ft.ListView(
                        controls=[self.users_table],
                        expand=True,
                    ),
                ],
                expand=True,
            ),
            expand=True,
            padding=8,
            visible=False,
        )

        # Navigation Bar for View Switching
        self.nav_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.SECURITY, label="Giám sát & Nhật ký"),
                ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Quản lý Người dùng"),
            ],
            selected_index=0,
            on_change=self._on_nav_change,
        )
        self.page.navigation_bar = self.nav_bar

        # Assemble Page
        self.page.add(
            ft.Column(
                [
                    cards_row,
                    controls_card,
                    self.logs_container,
                    self.users_container,
                ],
                expand=True,
                spacing=12,
            )
        )

        # Initial data population
        self.refresh_all()
        if not self.is_android and self.serial_bridge:
            self.serial_bridge.start()

    def _update_door_ui(self, detail: str = "") -> None:
        """Renders updated door status to UI controls."""
        try:
            if self.door_state == "OPEN":
                self.door_icon.name = ft.Icons.LOCK_OPEN
                self.door_icon.color = ft.Colors.GREEN
                self.door_label.value = "CỬA ĐANG MỞ"
                self.door_label.color = ft.Colors.GREEN
                self.door_desc.value = detail or "Mở khóa thành công (Relay kích hoạt 3s)"
            elif self.door_state == "LOCKED":
                self.door_icon.name = ft.Icons.WARNING
                self.door_icon.color = ft.Colors.RED
                self.door_label.value = "CẢNH BÁO: KHÓA TẠM"
                self.door_label.color = ft.Colors.RED
                self.door_desc.value = detail or "Hệ thống bị khóa 30s sau 3 lần sai"
            else:  # CLOSED
                self.door_icon.name = ft.Icons.LOCK
                self.door_icon.color = ft.Colors.AMBER
                self.door_label.value = "CỬA ĐANG ĐÓNG"
                self.door_label.color = ft.Colors.AMBER
                self.door_desc.value = detail or "Chờ tín hiệu từ PIC16F877A U1"

            self.page.update()
        except Exception:
            pass

    def _update_serial_ui(self) -> None:
        """Renders updated serial connection state to UI controls."""
        if self.is_android:
            return
        try:
            if self.serial_state == "CONNECTED":
                self.serial_icon.name = ft.Icons.CABLE
                self.serial_icon.color = ft.Colors.GREEN
                self.serial_label.value = "ĐÃ KẾT NỐI"
                self.serial_label.color = ft.Colors.GREEN
                port = getattr(self.serial_bridge, "port", "COM2")
                self.serial_desc.value = f"Cổng {port} đang mở | Baud: 9600 8N1"
            elif self.serial_state == "RECONNECTING":
                self.serial_icon.name = ft.Icons.SYNC
                self.serial_icon.color = ft.Colors.AMBER
                self.serial_label.value = "ĐANG KẾT NỐI LẠI..."
                self.serial_label.color = ft.Colors.AMBER
                self.serial_desc.value = "Đang tự động thử kết nối cổng COM..."
            else:  # DISCONNECTED
                self.serial_icon.name = ft.Icons.CABLE
                self.serial_icon.color = ft.Colors.RED
                self.serial_label.value = "MẤT KẾT NỐI"
                self.serial_label.color = ft.Colors.RED
                self.serial_desc.value = "Cổng COM đã ngắt hoặc chưa cắm cáp"

            self.page.update()
        except Exception:
            pass

    def _on_nav_change(self, e: ft.ControlEvent) -> None:
        """Handles switching between Dashboard/Logs view and Users view."""
        idx = e.control.selected_index
        self.current_view_index = idx
        if idx == 0:
            self.logs_container.visible = True
            self.users_container.visible = False
        else:
            self.logs_container.visible = False
            self.users_container.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    def _on_reconnect_click(self, e: ft.ControlEvent) -> None:
        """Handles manual reconnect click on desktop."""
        if self.is_android or not self.serial_bridge:
            return
        if hasattr(self, "port_input") and self.port_input.value:
            self.serial_bridge.port = self.port_input.value.strip()

        # Restart bridge
        try:
            self.serial_bridge.stop()
            self.serial_bridge.start()
            self.set_serial_state("RECONNECTING")
        except Exception as ex:
            self.set_serial_state("DISCONNECTED")

    def _on_sim_event(self, event_type: str) -> None:
        """Triggers a simulated event for Android demo mode."""
        sim = generate_simulated_event(event_type)
        if sim["status"] == "SUCCESS":
            self.set_door_state("OPEN", "Mô phỏng: Mở cửa thành công")
        elif sim["status"] == "LOCKOUT":
            self.set_door_state("LOCKED", "Mô phỏng: Khóa tạm báo động 30s")
        else:
            self.set_door_state("CLOSED", "Mô phỏng: Nhập sai mã PIN")
        self.refresh_logs()

    def refresh_logs(self) -> None:
        """Fetches and displays the latest access logs."""
        raw_logs = []
        if self.is_android:
            raw_logs = get_demo_logs(limit=25)
        else:
            if self.auth_service:
                raw_logs = self.auth_service.get_logs(limit=25)

        rows = []
        for log in raw_logs:
            status = log.get("status", "")
            if status == "SUCCESS":
                status_color = ft.Colors.GREEN
            elif status == "LOCKOUT":
                status_color = ft.Colors.RED
            else:
                status_color = ft.Colors.ORANGE

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(log.get("timestamp", "")))),
                        ft.DataCell(ft.Text(str(log.get("event_type", "")))),
                        ft.DataCell(ft.Text(status, color=status_color, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(str(log.get("detail", "")))),
                    ]
                )
            )

        self.log_table.rows = rows
        try:
            self.page.update()
        except Exception:
            pass

    def clear_logs_display(self) -> None:
        """Clears the table rows in the UI."""
        self.log_table.rows.clear()
        if self.is_android:
            clear_demo_logs()
        try:
            self.page.update()
        except Exception:
            pass

    def refresh_users(self) -> None:
        """Fetches and displays the registered users."""
        users = []
        if self.is_android:
            users = get_demo_users()
        else:
            if self.auth_service:
                users = self.auth_service.get_users()

        rows = []
        for u in users:
            role = u.get("role", "user")
            role_color = ft.Colors.LIGHT_BLUE if role == "admin" else ft.Colors.WHITE70
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(u.get("id", "")))),
                        ft.DataCell(ft.Text(str(u.get("name", "")))),
                        ft.DataCell(ft.Text(role, color=role_color, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text("****", color=ft.Colors.WHITE54)),
                    ]
                )
            )

        self.users_table.rows = rows
        try:
            self.page.update()
        except Exception:
            pass

    def refresh_all(self) -> None:
        """Refreshes all views and indicators."""
        self.refresh_logs()
        self.refresh_users()
        if not self.is_android and self.serial_bridge:
            state = "CONNECTED" if self.serial_bridge.is_connected() else "DISCONNECTED"
            self.set_serial_state(state)

    def close(self) -> None:
        """Gracefully shuts down bridge and timers."""
        if self._door_timer and self._door_timer.is_alive():
            self._door_timer.cancel()
        if self.serial_bridge:
            try:
                self.serial_bridge.stop()
            except Exception:
                pass


def main(page: ft.Page) -> DoorLockApp:
    """Main application entry point."""
    app = DoorLockApp(page)
    app.build_ui()
    return app


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    elif hasattr(ft, "app"):
        ft.app(target=main)
