"""
Smart PIN Door Lock System - Multiplatform Flet Application
Unified single codebase supporting Windows Desktop and Android.

Features:
- Real-time door status indicator: CLOSED, OPEN (unlocked 3s), LOCKED (alarm).
- Serial connection status: CONNECTED, DISCONNECTED, RECONNECTING (Desktop only).
- Live access log table: Timestamp, Event Type, Status (SUCCESS, FAILED, LOCKOUT), Detail (PIN masked).
- Admin Authentication (Default: admin / 1234):
  - View real unmasked entered PINs from past attempts (toggleable in real-time).
  - Edit/change 4-digit PIN for any user directly from the interface.
  - Configure and change COM port connection dynamically.
  - Set and manage Master PIN (universal fixed master key that always unlocks).
  - Add and delete users.
- User management view: Configured user profiles with masked PINs by default, editable by Admin.
- Interactive controls: Open/Reconnect COM, Refresh logs, Clear log display.
- Runtime platform separation:
  - On Desktop: Initializes SerialBridge and AuthService with auto-reconnect resilience.
  - On Android: Runs in Demo/Monitoring mode using demo_data.py; serial controls are hidden.
  - CRITICAL CONSTRAINT: Under Android, NEVER import pyserial, auth_service, or data/.
"""

import sys
import os
import time
import re
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

        # Admin state
        self.is_admin: bool = False
        self.show_raw_pins: bool = False

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
            configured_port = "COM2"
            if hasattr(self.auth_service, "config_file") and self.auth_service.config_file.is_file():
                try:
                    import json
                    with open(self.auth_service.config_file, "r", encoding="utf-8") as f:
                        c = json.load(f)
                    configured_port = c.get("serial", {}).get("port", "COM2")
                except Exception:
                    pass

            self.serial_bridge = serial_cls(
                port=configured_port,
                baudrate=9600,
                lockout_duration=30.0,
                auth_service=self.auth_service,
                on_state_change=self.handle_serial_state_change,
                on_log=self.handle_serial_log,
                serial_instance=self.injected_serial,
            )
            self.serial_state = "CONNECTED" if self.serial_bridge.is_connected() else "DISCONNECTED"
        except Exception:
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

        self.admin_btn = ft.FilledButton(
            "Đăng nhập Admin",
            icon=ft.Icons.LOCK_OUTLINE,
            bgcolor=ft.Colors.BLUE_900,
            on_click=self._on_admin_btn_click,
        )

        self.page.appbar = ft.AppBar(
            title=ft.Column(
                [
                    ft.Text("HỆ THỐNG KHÓA CỬA THÔNG MINH PIN", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitle_text, size=12, color=ft.Colors.WHITE_70),
                ],
                spacing=2,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            center_title=False,
            actions=[self.admin_btn, ft.Container(width=8)],
        )

        # Status Cards
        self.door_icon = ft.Icon(ft.Icons.LOCK, size=48, color=ft.Colors.AMBER)
        self.door_label = ft.Text("CỬA ĐANG ĐÓNG", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER)
        self.door_desc = ft.Text("Chờ tín hiệu từ PIC16F877A U1", size=12, color=ft.Colors.WHITE_60)

        self.door_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        self.door_icon,
                        ft.Column(
                            [
                                ft.Text("TRẠNG THÁI CỬA", size=11, color=ft.Colors.WHITE_54, weight=ft.FontWeight.BOLD),
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
        current_port_name = "COM2"
        if not self.is_android and self.serial_bridge:
            current_port_name = getattr(self.serial_bridge, "port", "COM2")

        if not self.is_android:
            self.serial_icon = ft.Icon(ft.Icons.CABLE, size=48, color=ft.Colors.RED)
            self.serial_label = ft.Text("MẤT KẾT NỐI", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED)
            self.serial_desc = ft.Text(f"Cổng COM: {current_port_name} | Baud: 9600 8N1", size=12, color=ft.Colors.WHITE_60)
            self.serial_card = ft.Card(
                content=ft.Container(
                    content=ft.Row(
                        [
                            self.serial_icon,
                            ft.Column(
                                [
                                    ft.Text("KẾT NỐI SERIAL COMPIM", size=11, color=ft.Colors.WHITE_54, weight=ft.FontWeight.BOLD),
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
            self.serial_desc = ft.Text("Độc lập phần cứng | Không yêu cầu PySerial", size=12, color=ft.Colors.WHITE_60)
            self.serial_card = ft.Card(
                content=ft.Container(
                    content=ft.Row(
                        [
                            self.serial_icon,
                            ft.Column(
                                [
                                    ft.Text("NỀN TẢNG ANDROID", size=11, color=ft.Colors.WHITE_54, weight=ft.FontWeight.BOLD),
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
                value=current_port_name,
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

        # Message Banner (for alerts and success notices)
        self.status_msg_text = ft.Text("", size=13, weight=ft.FontWeight.W_500)
        self.status_banner = ft.Container(
            content=self.status_msg_text,
            padding=8,
            border_radius=6,
            visible=False,
        )

        # Raw PIN Switch in Log view
        self.raw_pin_switch = ft.Switch(
            label="Hiện mã PIN thật các lần nhập trước",
            value=False,
            visible=False,
            on_change=self._on_toggle_raw_pins,
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
                            ft.Row(
                                [
                                    ft.Text("NHẬT KÝ RA VÀO THỜI GIAN THỰC", size=15, weight=ft.FontWeight.BOLD),
                                    ft.Text("(Dữ liệu bảo mật - PIN mặc định che dạng ****)", size=12, color=ft.Colors.WHITE_54),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                            self.raw_pin_switch,
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

        # Admin Control Panel (Inside User Management tab)
        master_pin_val = "1234"
        if not self.is_android and self.auth_service:
            master_pin_val = getattr(self.auth_service, "master_pin", "1234")

        self.master_pin_input = ft.TextField(
            label="Mật khẩu chính cố định (Master PIN)",
            value=master_pin_val,
            width=220,
            dense=True,
        )
        self.admin_port_input = ft.TextField(
            label="Cổng COM (VD: COM1, COM2...)",
            value=current_port_name,
            width=180,
            dense=True,
        )
        self.new_user_id_input = ft.TextField(label="Mã User (VD: USR003)", width=130, dense=True)
        self.new_user_name_input = ft.TextField(label="Tên Người Dùng", width=180, dense=True)
        self.new_user_pin_input = ft.TextField(label="PIN 4 số", width=110, dense=True)

        self.admin_controls_panel = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS, color=ft.Colors.AMBER, size=22),
                                ft.Text("BẢNG ĐIỀU KHIỂN DÀNH CHO QUẢN TRỊ VIÊN", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER),
                            ],
                            spacing=6,
                        ),
                        ft.Divider(),
                        # Section 1: Master PIN & COM Port
                        ft.Row(
                            [
                                self.master_pin_input,
                                ft.FilledButton("Lưu Master PIN", icon=ft.Icons.VPN_KEY, on_click=self._on_save_master_pin),
                                ft.Container(width=16),
                                self.admin_port_input,
                                ft.FilledButton("Lưu Cổng COM", icon=ft.Icons.SAVE, on_click=self._on_save_com_port),
                            ],
                            wrap=True,
                            spacing=10,
                        ),
                        # Section 2: Add New User
                        ft.Row(
                            [
                                self.new_user_id_input,
                                self.new_user_name_input,
                                self.new_user_pin_input,
                                ft.FilledButton("Thêm Người Dùng", icon=ft.Icons.PERSON_ADD, bgcolor=ft.Colors.GREEN_800, on_click=self._on_add_user),
                            ],
                            wrap=True,
                            spacing=10,
                        ),
                    ],
                    spacing=10,
                ),
                padding=14,
            ),
            visible=False,
        )

        # Admin Login Box (visible when not logged in inside User tab)
        self.login_user_input = ft.TextField(label="Tên tài khoản", value="admin", width=160, dense=True)
        self.login_pass_input = ft.TextField(label="Mật khẩu", value="1234", password=True, can_reveal_password=True, width=160, dense=True)
        self.admin_login_box = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SHIELD, color=ft.Colors.LIGHT_BLUE, size=24),
                        ft.Column(
                            [
                                ft.Text("ĐĂNG NHẬP ADMIN ĐỂ CHỈNH SỬA MẬT KHẨU & CỔNG", size=13, weight=ft.FontWeight.BOLD),
                                ft.Text("Tài khoản mặc định: admin | Mật khẩu: 1234", size=11, color=ft.Colors.WHITE_54),
                            ],
                            spacing=2,
                        ),
                        ft.Container(width=10),
                        self.login_user_input,
                        self.login_pass_input,
                        ft.FilledButton("Đăng Nhập", icon=ft.Icons.LOGIN, bgcolor=ft.Colors.BLUE_800, on_click=self._on_admin_login_submit),
                    ],
                    wrap=True,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=12,
            ),
            visible=True,
        )

        # User Management Table
        self.users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Mã Người Dùng", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Họ và Tên", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Vai Trò", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Mã PIN Bảo Mật", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Thao Tác (Admin)", weight=ft.FontWeight.BOLD)),
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
                            ft.Text("DANH SÁCH NGƯỜI DÙNG & CẤU HÌNH HỆ THỐNG", size=15, weight=ft.FontWeight.BOLD),
                            ft.Text("(Cập nhật trực tiếp không cần khởi động lại)", size=12, color=ft.Colors.WHITE_54),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self.admin_login_box,
                    self.admin_controls_panel,
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
                    self.status_banner,
                    self.logs_container,
                    self.users_container,
                ],
                expand=True,
                spacing=10,
            )
        )

        # Initial data population
        self.refresh_all()
        if not self.is_android and self.serial_bridge:
            self.serial_bridge.start()

    def _show_message(self, message: str, success: bool = True) -> None:
        """Displays informative banner message."""
        try:
            self.status_msg_text.value = message
            self.status_msg_text.color = ft.Colors.GREEN_200 if success else ft.Colors.RED_200
            self.status_banner.bgcolor = ft.Colors.GREEN_900 if success else ft.Colors.RED_900
            self.status_banner.visible = True
            self.page.update()
        except Exception:
            pass

    def _on_admin_btn_click(self, e: ft.ControlEvent) -> None:
        """Handles click on the top-right Admin button in AppBar."""
        if self.is_admin:
            # Logout
            self.is_admin = False
            self.show_raw_pins = False
            self.admin_btn.text = "Đăng nhập Admin"
            self.admin_btn.icon = ft.Icons.LOCK_OUTLINE
            self.admin_btn.bgcolor = ft.Colors.BLUE_900
            self.raw_pin_switch.visible = False
            self.raw_pin_switch.value = False
            self.admin_controls_panel.visible = False
            self.admin_login_box.visible = True
            self.refresh_all()
            self._show_message("Đã đăng xuất tài khoản Quản trị viên.", success=True)
        else:
            # Switch to Users & Admin tab
            self.current_view_index = 1
            if hasattr(self, "nav_bar"):
                self.nav_bar.selected_index = 1
            self.logs_container.visible = False
            self.users_container.visible = True
            self._show_message("Vui lòng nhập tài khoản và mật khẩu admin (mặc định: admin / 1234).", success=True)
            try:
                self.page.update()
            except Exception:
                pass

    def _on_admin_login_submit(self, e: ft.ControlEvent) -> None:
        """Validates admin credentials."""
        username = self.login_user_input.value.strip()
        password = self.login_pass_input.value.strip()

        is_valid = False
        if not self.is_android and self.auth_service:
            is_valid = self.auth_service.verify_admin_login(username, password)
        else:
            # Demo validation
            is_valid = (username.lower() == "admin" and password == "1234")

        if is_valid:
            self.is_admin = True
            self.admin_btn.text = "Admin (Đăng xuất)"
            self.admin_btn.icon = ft.Icons.LOGOUT
            self.admin_btn.bgcolor = ft.Colors.RED_900
            self.raw_pin_switch.visible = True
            self.admin_controls_panel.visible = True
            self.admin_login_box.visible = False
            self.refresh_all()
            self._show_message("Đăng nhập Admin thành công! Đã kích hoạt quyền chỉnh sửa và xem PIN.", success=True)
        else:
            self._show_message("Tên đăng nhập hoặc mật khẩu Admin không đúng! (Mặc định: admin / 1234)", success=False)

    def _on_toggle_raw_pins(self, e: ft.ControlEvent) -> None:
        """Toggles between masked '****' and real entered PINs for Admin audit."""
        self.show_raw_pins = e.control.value
        self.refresh_logs()
        if self.show_raw_pins:
            self._show_message("Chế độ Admin: Đang hiển thị mã PIN thật của các lần nhập trước.", success=True)
        else:
            self._show_message("Đã ẩn mã PIN thật (hiển thị **** theo chuẩn bảo mật).", success=True)

    def _on_save_master_pin(self, e: ft.ControlEvent) -> None:
        """Updates the fixed Master PIN."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để thực hiện thao tác này!", success=False)
            return

        new_pin = self.master_pin_input.value.strip()
        if not re.match(r"^\d{4}$", new_pin):
            self._show_message("Mật khẩu chính (Master PIN) phải bao gồm đúng 4 chữ số!", success=False)
            return

        if not self.is_android and self.auth_service:
            success, msg = self.auth_service.set_master_pin(new_pin)
            self._show_message(msg, success=success)
        else:
            self._show_message(f"Demo: Đã lưu Mật khẩu chính cố định là {new_pin}.", success=True)

    def _on_save_com_port(self, e: ft.ControlEvent) -> None:
        """Updates and reconnects serial COM port."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để thay đổi cổng COM!", success=False)
            return

        new_port = self.admin_port_input.value.strip()
        if not new_port:
            self._show_message("Tên cổng COM không được để trống!", success=False)
            return

        if not self.is_android and self.serial_bridge:
            self.serial_bridge.port = new_port
            if hasattr(self, "port_input"):
                self.port_input.value = new_port
            if self.auth_service:
                self.auth_service.save_serial_port_to_config(new_port)
            try:
                self.serial_bridge.stop()
                self.serial_bridge.start()
                self.set_serial_state("RECONNECTING")
            except Exception:
                self.set_serial_state("DISCONNECTED")
            self._show_message(f"Đã lưu và chuyển kết nối sang cổng {new_port}!", success=True)
        else:
            self._show_message(f"Demo: Đã đổi cổng COM sang {new_port}.", success=True)

    def _on_add_user(self, e: ft.ControlEvent) -> None:
        """Adds a new user record."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để thêm người dùng!", success=False)
            return

        uid = self.new_user_id_input.value.strip()
        name = self.new_user_name_input.value.strip()
        pin = self.new_user_pin_input.value.strip()

        if not self.is_android and self.auth_service:
            success, msg = self.auth_service.add_user(uid, name, pin)
            self._show_message(msg, success=success)
            if success:
                self.new_user_id_input.value = ""
                self.new_user_name_input.value = ""
                self.new_user_pin_input.value = ""
                self.refresh_users()
        else:
            self._show_message("Demo: Thêm người dùng thành công.", success=True)

    def _on_edit_user_pin(self, user_id: str, user_name: str) -> None:
        """Opens prompt to update user PIN."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để sửa mã PIN!", success=False)
            return

        pin_input = ft.TextField(label="Mã PIN 4 số mới", width=160, dense=True)

        def on_confirm_click(ev):
            new_p = pin_input.value.strip()
            if not self.is_android and self.auth_service:
                s, m = self.auth_service.update_user_pin(user_id, new_p)
                self._show_message(m, success=s)
                if s:
                    self.refresh_users()
            else:
                self._show_message(f"Demo: Đã đổi mã PIN cho {user_name} thành {new_p}.", success=True)

            if hasattr(self.page, "pop_dialog"):
                self.page.pop_dialog()
            elif hasattr(dlg, "open"):
                dlg.open = False
                self.page.update()

        def on_cancel_click(ev):
            if hasattr(self.page, "pop_dialog"):
                self.page.pop_dialog()
            elif hasattr(dlg, "open"):
                dlg.open = False
                self.page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Đổi mã PIN: {user_name} ({user_id})"),
            content=ft.Column(
                [
                    ft.Text("Nhập mã PIN 4 chữ số mới cho người dùng:"),
                    pin_input,
                ],
                tight=True,
                spacing=10,
            ),
            actions=[
                ft.TextButton("Hủy", on_click=on_cancel_click),
                ft.FilledButton("Lưu PIN", on_click=on_confirm_click),
            ],
        )

        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(dlg)
        elif hasattr(self.page, "overlay"):
            self.page.overlay.append(dlg)
            dlg.open = True
            self.page.update()

    def _on_delete_user(self, user_id: str) -> None:
        """Deletes user record."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để xóa người dùng!", success=False)
            return

        if not self.is_android and self.auth_service:
            s, m = self.auth_service.delete_user(user_id)
            self._show_message(m, success=s)
            if s:
                self.refresh_users()
        else:
            self._show_message(f"Demo: Đã xóa người dùng {user_id}.", success=True)

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
            port = getattr(self.serial_bridge, "port", "COM2") if self.serial_bridge else "COM2"
            if self.serial_state == "CONNECTED":
                self.serial_icon.name = ft.Icons.CABLE
                self.serial_icon.color = ft.Colors.GREEN
                self.serial_label.value = "ĐÃ KẾT NỐI"
                self.serial_label.color = ft.Colors.GREEN
                self.serial_desc.value = f"Cổng {port} đang mở | Baud: 9600 8N1"
            elif self.serial_state == "RECONNECTING":
                self.serial_icon.name = ft.Icons.SYNC
                self.serial_icon.color = ft.Colors.AMBER
                self.serial_label.value = "ĐANG KẾT NỐI LẠI..."
                self.serial_label.color = ft.Colors.AMBER
                self.serial_desc.value = f"Đang tự động thử kết nối cổng {port}..."
            else:  # DISCONNECTED
                self.serial_icon.name = ft.Icons.CABLE
                self.serial_icon.color = ft.Colors.RED
                self.serial_label.value = "MẤT KẾT NỐI"
                self.serial_label.color = ft.Colors.RED
                self.serial_desc.value = f"Cổng {port} đã ngắt hoặc chưa cắm cáp"

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
            new_p = self.port_input.value.strip()
            self.serial_bridge.port = new_p
            if hasattr(self, "admin_port_input"):
                self.admin_port_input.value = new_p

        # Restart bridge
        try:
            self.serial_bridge.stop()
            self.serial_bridge.start()
            self.set_serial_state("RECONNECTING")
        except Exception:
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
                raw_logs = self.auth_service.get_logs(limit=25, as_admin=self.is_admin)

        # Configure columns based on Admin toggle
        if self.is_admin and self.show_raw_pins:
            self.log_table.columns = [
                ft.DataColumn(ft.Text("Thời gian", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Sự kiện", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Trạng thái", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Chi tiết", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Mã PIN Đã Nhập", weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW)),
            ]
        else:
            self.log_table.columns = [
                ft.DataColumn(ft.Text("Thời gian", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Sự kiện", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Trạng thái", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Chi tiết (Mã PIN bảo mật ****)", weight=ft.FontWeight.BOLD)),
            ]

        rows = []
        for log in raw_logs:
            status = log.get("status", "")
            if status == "SUCCESS":
                status_color = ft.Colors.GREEN
            elif status == "LOCKOUT":
                status_color = ft.Colors.RED
            else:
                status_color = ft.Colors.ORANGE

            cells = [
                ft.DataCell(ft.Text(str(log.get("timestamp", "")))),
                ft.DataCell(ft.Text(str(log.get("event_type", "")))),
                ft.DataCell(ft.Text(status, color=status_color, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(str(log.get("detail", "")))),
            ]
            if self.is_admin and self.show_raw_pins:
                raw_pin_str = log.get("raw_pin", "")
                if not raw_pin_str and "PIN:" in log.get("detail", ""):
                    raw_pin_str = "****"
                cells.append(
                    ft.DataCell(ft.Text(raw_pin_str if raw_pin_str else "(Không rõ)", color=ft.Colors.YELLOW_ACCENT, weight=ft.FontWeight.BOLD))
                )

            rows.append(ft.DataRow(cells=cells))

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
                users = self.auth_service.get_users(mask_pin=(not self.is_admin))

        rows = []
        for u in users:
            uid = str(u.get("id", ""))
            uname = str(u.get("name", ""))
            role = u.get("role", "user")
            role_color = ft.Colors.LIGHT_BLUE if role == "admin" else ft.Colors.WHITE_70
            pin_str = str(u.get("pin", "****"))

            # Build action buttons
            if self.is_admin:
                action_control = ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.EDIT,
                            tooltip=f"Đổi PIN cho {uname}",
                            icon_color=ft.Colors.AMBER,
                            on_click=lambda _, i=uid, n=uname: self._on_edit_user_pin(i, n),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip=f"Xóa {uname}",
                            icon_color=ft.Colors.RED_400,
                            on_click=lambda _, i=uid: self._on_delete_user(i),
                        ),
                    ],
                    spacing=2,
                )
            else:
                action_control = ft.Text("🔒 Cần quyền Admin", size=11, color=ft.Colors.WHITE_38)

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(uid)),
                        ft.DataCell(ft.Text(uname)),
                        ft.DataCell(ft.Text(role, color=role_color, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(pin_str, color=ft.Colors.GREEN_ACCENT if self.is_admin else ft.Colors.WHITE_54, weight=ft.FontWeight.BOLD if self.is_admin else ft.FontWeight.NORMAL)),
                        ft.DataCell(action_control),
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
