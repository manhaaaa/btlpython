"""
Main Application Controller and View: DoorLockApp.
Coordinates UI components, hardware serial bridge, authentication services, and periodic logging.
"""
import inspect
import json
import re
import threading
from typing import Optional, Any, List, Dict

import flet as ft

from app.core.platform import is_android_platform, load_desktop_modules, get_available_com_ports
from app.core.periodic_logger import PeriodicStatusLogger
from app.mock.demo_data import get_demo_users, get_demo_logs, clear_demo_logs, generate_simulated_event
from app.ui.components.status_cards import StatusCardsComponent
from app.ui.components.controls_bar import ControlsBarComponent
from app.ui.components.log_view import LogViewComponent
from app.ui.components.user_view import UserManagementComponent


class DoorLockApp:
    """
    Main application controller managing state, hardware bridge, auth, and UI composition.
    """

    def __init__(
        self,
        page: ft.Page,
        is_android: Optional[bool] = None,
        serial_instance: Optional[Any] = None,
        auth_service: Optional[Any] = None,
    ):
        self.page = page
        self.is_android = is_android if is_android is not None else is_android_platform(page)
        self.injected_serial = serial_instance
        self.injected_auth = auth_service

        # State tracking
        self.door_state: str = "CLOSED"  # CLOSED, OPEN, LOCKED
        self.serial_state: str = "DISCONNECTED"  # CONNECTED, DISCONNECTED, RECONNECTING, etc.
        self.current_view_index: int = 0

        # Admin state
        self.is_admin: bool = False
        self.show_raw_pins: bool = False

        # Backend handles
        self.auth_service = None
        self.serial_bridge = None
        self._periodic_logger: Optional[PeriodicStatusLogger] = None

        # Initialize Desktop Backend if applicable
        if not self.is_android:
            self._init_desktop_backend()

        # Initialize Periodic Logger (every 30 minutes = 1800s)
        self._periodic_logger = PeriodicStatusLogger(
            status_provider=self._get_current_status_summary,
            interval_seconds=1800,
        )
        self._periodic_logger.start()

    def _get_current_status_summary(self) -> Dict[str, Any]:
        """Provides snapshot data for the periodic status logger."""
        success_count = 0
        failed_count = 0
        if not self.is_android and self.auth_service:
            try:
                logs = self.auth_service.get_logs(limit=100)
                success_count = sum(1 for l in logs if l.get("status") == "SUCCESS")
                failed_count = sum(1 for l in logs if l.get("status") in ("FAILED", "LOCKOUT"))
            except Exception:
                pass

        port_name = "COM6"
        if not self.is_android and self.serial_bridge:
            port_name = getattr(self.serial_bridge, "port", "COM6")

        return {
            "door_state": self.door_state,
            "serial_state": self.serial_state,
            "port": port_name,
            "total_success": success_count,
            "total_failed": failed_count,
        }

    def _init_desktop_backend(self) -> None:
        """Initializes AuthService and SerialBridge for Desktop operation."""
        try:
            serial_cls, auth_cls = load_desktop_modules()
            if self.injected_auth is not None:
                self.auth_service = self.injected_auth
            else:
                self.auth_service = auth_cls()

            configured_port = "COM6"
            if hasattr(self.auth_service, "config_file") and self.auth_service.config_file and self.auth_service.config_file.is_file():
                try:
                    with open(self.auth_service.config_file, "r", encoding="utf-8") as f:
                        c = json.load(f)
                    configured_port = c.get("serial", {}).get("port", "COM6")
                except Exception:
                    pass

            master_pin_val = (
                getattr(self.auth_service, "master_pin", "1234")
                if self.auth_service
                else "1234"
            )

            self.serial_bridge = serial_cls(
                port=configured_port,
                baudrate=9600,
                lockout_duration=30.0,
                auth_service=self.auth_service,
                master_pin=master_pin_val,
                on_state_change=self.handle_serial_state_change,
                on_log=self.handle_serial_log,
                serial_instance=self.injected_serial,
            )
            if self.serial_bridge.is_connected():
                self.serial_state = "CONNECTED" if getattr(self.serial_bridge, "_pic_alive", False) else "PORT_OPEN"
            else:
                self.serial_state = "DISCONNECTED"
        except Exception:
            self.serial_state = "DISCONNECTED"

    def handle_serial_state_change(self, state: str) -> None:
        """Callback invoked by SerialBridge when connection or auth state transitions."""
        if state == "ACCESS_GRANTED":
            self.set_door_state("OPEN", "Mở khóa thành công - Cửa mở, chờ nhấn nút để đóng")
        elif state == "DOOR_CLOSED":
            self.set_door_state("CLOSED", "Cửa đã đóng (nhấn nút đóng cửa)")
        elif state == "LOCKED":
            self.set_door_state("LOCKED", "Cảnh báo: Khóa tạm sau 3 lần nhập sai")
        elif state == "ACCESS_DENIED":
            self.set_door_state("CLOSED", "Từ chối truy cập: Mã PIN không đúng")
        elif state in ("CONNECTED", "PIC_READY", "PORT_OPEN", "LISTENING", "DISCONNECTED", "RECONNECTING"):
            self.set_serial_state(state)

        self.refresh_logs()

    def handle_serial_log(self, message: str) -> None:
        """Handles serial log messages."""
        pass

    def set_door_state(self, new_state: str, detail: str = "") -> None:
        """Updates the door state indicator."""
        self.door_state = new_state
        self.status_cards.update_door(new_state, detail)
        try:
            self.page.update()
        except Exception:
            pass

    def set_serial_state(self, new_state: str) -> None:
        """Updates the serial connection state indicator."""
        self.serial_state = new_state
        port = getattr(self.serial_bridge, "port", "COM6") if self.serial_bridge else "COM6"
        self.status_cards.update_serial(new_state, port)
        try:
            self.page.update()
        except Exception:
            pass

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

        # 1. Status Cards Component
        current_port_name = "COM6"
        if not self.is_android and self.serial_bridge:
            current_port_name = getattr(self.serial_bridge, "port", "COM6")

        self.status_cards = StatusCardsComponent(
            is_android=self.is_android,
            initial_port=current_port_name,
        )

        # 2. Controls Bar Component
        avail_ports = get_available_com_ports() if not self.is_android else []
        self.controls_bar = ControlsBarComponent(
            is_android=self.is_android,
            current_port=current_port_name,
            available_ports=avail_ports,
            on_port_change=self._on_port_dropdown_change,
            on_reconnect=self._on_reconnect_click,
            on_refresh=self.refresh_all,
            on_clear=self.clear_logs_display,
            on_log_excel=self._on_manual_log_excel,
            on_sim_event=self._on_sim_event if self.is_android else None,
        )

        # 3. Message Banner
        self.status_msg_text = ft.Text("", size=13, weight=ft.FontWeight.W_500)
        self.status_banner = ft.Container(
            content=self.status_msg_text,
            padding=8,
            border_radius=6,
            visible=False,
        )

        # 4. Log View Component
        self.log_view = LogViewComponent(
            on_toggle_raw_pins=self._on_toggle_raw_pins,
        )

        # 5. User Management Component
        master_pin_val = "1234"
        if not self.is_android and self.auth_service:
            master_pin_val = getattr(self.auth_service, "master_pin", "1234")

        self.user_view = UserManagementComponent(
            current_port=current_port_name,
            master_pin_val=master_pin_val,
            on_admin_login=self._on_admin_login_submit,
            on_save_master_pin=self._on_save_master_pin,
            on_save_com_port=self._on_save_com_port,
            on_add_user=self._on_add_user,
            on_edit_user_pin=self._on_edit_user_pin,
            on_delete_user=self._on_delete_user,
        )

        # Navigation Bar
        self.nav_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.SECURITY, label="Giám sát & Nhật ký"),
                ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Quản lý Người dùng"),
            ],
            selected_index=0,
            on_change=self._on_nav_change,
        )
        self.page.navigation_bar = self.nav_bar

        # Mount to page
        self.page.add(
            ft.Column(
                [
                    self.status_cards.cards_row,
                    self.controls_bar.card,
                    self.status_banner,
                    self.log_view.container,
                    self.user_view.container,
                ],
                expand=True,
                spacing=10,
            )
        )

        # Initial data population
        self.refresh_all()
        if not self.is_android and self.serial_bridge:
            self.serial_bridge.start()
            if self.serial_bridge.is_connected():
                self.set_serial_state("CONNECTED")

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

    def _on_manual_log_excel(self) -> None:
        """Manually triggers an Excel status snapshot row."""
        if self._periodic_logger:
            ok = self._periodic_logger.log_snapshot(trigger_note="Thu cong (User click)")
            if ok:
                self._show_message("Đã ghi thành công trạng thái vào file data/periodic_status_log.csv!", success=True)
            else:
                self._show_message("Không thể ghi log vào thư mục data. Vui lòng kiểm tra quyền truy cập.", success=False)

    def _on_admin_btn_click(self, e: ft.ControlEvent) -> None:
        """Handles click on the top-right Admin button in AppBar."""
        if self.is_admin:
            # Logout
            self.is_admin = False
            self.show_raw_pins = False
            self.admin_btn.text = "Đăng nhập Admin"
            self.admin_btn.icon = ft.Icons.LOCK_OUTLINE
            self.admin_btn.bgcolor = ft.Colors.BLUE_900
            self.log_view.raw_pin_switch.visible = False
            self.log_view.raw_pin_switch.value = False
            self.user_view.set_admin_mode(False)
            self.refresh_all()
            self._show_message("Đã đăng xuất tài khoản Quản trị viên.", success=True)
        else:
            # Switch to Users & Admin tab
            self.current_view_index = 1
            if hasattr(self, "nav_bar"):
                self.nav_bar.selected_index = 1
            self.log_view.container.visible = False
            self.user_view.container.visible = True
            self._show_message("Vui lòng nhập tài khoản và mật khẩu admin (mặc định: admin / 1234).", success=True)
            try:
                self.page.update()
            except Exception:
                pass

    def _on_admin_login_submit(self, e: ft.ControlEvent) -> None:
        """Validates admin credentials."""
        username = self.user_view.login_user_input.value.strip()
        password = self.user_view.login_pass_input.value.strip()

        is_valid = False
        if not self.is_android and self.auth_service:
            is_valid = self.auth_service.verify_admin_login(username, password)
        else:
            is_valid = (username.lower() == "admin" and password == "1234")

        if is_valid:
            self.is_admin = True
            self.admin_btn.text = "Admin (Đăng xuất)"
            self.admin_btn.icon = ft.Icons.LOGOUT
            self.admin_btn.bgcolor = ft.Colors.RED_900
            self.log_view.raw_pin_switch.visible = True
            self.user_view.set_admin_mode(True)
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

        new_pin = self.user_view.master_pin_input.value.strip()
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

        new_port = self.user_view.admin_port_input.value.strip()
        if not new_port:
            self._show_message("Tên cổng COM không được để trống!", success=False)
            return

        if not self.is_android and self.serial_bridge:
            self.serial_bridge.port = new_port
            if hasattr(self.controls_bar, "port_dropdown"):
                self.controls_bar.port_dropdown.value = new_port
            if self.auth_service:
                self.auth_service.save_serial_port_to_config(new_port)
            self.set_serial_state("RECONNECTING")
            self._show_message(f"Đã lưu và đang chuyển kết nối sang cổng {new_port}...", success=True)

            def _reconnect_admin():
                try:
                    self.serial_bridge.stop()
                    self.serial_bridge.start()
                    if self.serial_bridge.is_connected():
                        self.set_serial_state("CONNECTED")
                        self._show_message(f"Đã kết nối thành công tới cổng {new_port}!", success=True)
                    else:
                        self.set_serial_state("DISCONNECTED")
                        self._show_message(f"Không thể mở cổng {new_port}. Vui lòng kiểm tra Proteus COMPIM.", success=False)
                except Exception:
                    self.set_serial_state("DISCONNECTED")

            threading.Thread(target=_reconnect_admin, name="AdminAsyncReconnectWorker", daemon=True).start()
        else:
            self._show_message(f"Demo: Đã đổi cổng COM sang {new_port}.", success=True)

    def _on_add_user(self, e: ft.ControlEvent) -> None:
        """Adds a new user record."""
        if not self.is_admin:
            self._show_message("Cần đăng nhập Admin để thêm người dùng!", success=False)
            return

        uid = self.user_view.new_user_id_input.value.strip()
        name = self.user_view.new_user_name_input.value.strip()
        pin = self.user_view.new_user_pin_input.value.strip()

        if not self.is_android and self.auth_service:
            success, msg = self.auth_service.add_user(uid, name, pin)
            self._show_message(msg, success=success)
            if success:
                self.user_view.new_user_id_input.value = ""
                self.user_view.new_user_name_input.value = ""
                self.user_view.new_user_pin_input.value = ""
                self.refresh_users()
        else:
            self._show_message("Demo: Thêm người dùng thành công.", success=True)

    def _on_edit_user_pin(self, user_id: str, user_name: str) -> None:
        """Opens dialog to update user PIN."""
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

    def _on_nav_change(self, e: ft.ControlEvent) -> None:
        """Handles switching between Dashboard/Logs view and Users view."""
        idx = e.control.selected_index
        self.current_view_index = idx
        if idx == 0:
            self.log_view.container.visible = True
            self.user_view.container.visible = False
        else:
            self.log_view.container.visible = False
            self.user_view.container.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    def _on_port_dropdown_change(self, e: ft.ControlEvent) -> None:
        """Handles selecting a new COM port from the dropdown."""
        ctrl = getattr(e, "control", None)
        new_p = str(getattr(ctrl, "value", None) or getattr(e, "data", None) or "COM6").strip()
        if hasattr(self.user_view, "admin_port_input"):
            self.user_view.admin_port_input.value = new_p
        if not self.is_android and self.serial_bridge:
            self.serial_bridge.port = new_p
        if not self.is_android and self.auth_service:
            try:
                self.auth_service.save_serial_port_to_config(new_p)
            except Exception:
                pass
        self._show_message(f"Đã chọn cổng {new_p}. Bấm 'Kết nối lại' để áp dụng.", success=True)

    def _on_reconnect_click(self, e: ft.ControlEvent) -> None:
        """Handles manual reconnect click asynchronously on worker thread."""
        if self.is_android or not self.serial_bridge:
            return
        if hasattr(self.controls_bar, "port_dropdown") and self.controls_bar.port_dropdown.value:
            new_p = str(self.controls_bar.port_dropdown.value).strip()
            self.serial_bridge.port = new_p
            if hasattr(self.user_view, "admin_port_input"):
                self.user_view.admin_port_input.value = new_p
            if self.auth_service:
                try:
                    self.auth_service.save_serial_port_to_config(new_p)
                except Exception:
                    pass

        self.set_serial_state("RECONNECTING")
        self._show_message(f"Đang kết nối lại cổng {self.serial_bridge.port}...", success=True)

        def _reconnect_worker():
            try:
                self.serial_bridge.stop()
                self.serial_bridge.start()
                if self.serial_bridge.is_connected():
                    self.set_serial_state("CONNECTED")
                    self._show_message(f"Đã kết nối thành công tới cổng {self.serial_bridge.port}!", success=True)
                else:
                    self.set_serial_state("DISCONNECTED")
                    self._show_message(f"Không thể mở cổng {self.serial_bridge.port}. Vui lòng kiểm tra Proteus COMPIM.", success=False)
            except Exception as ex:
                self.set_serial_state("DISCONNECTED")
                self._show_message(f"Lỗi kết nối cổng: {ex}", success=False)

        threading.Thread(target=_reconnect_worker, name="AsyncReconnectWorker", daemon=True).start()

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

        self.log_view.update_rows(raw_logs, is_admin=self.is_admin, show_raw_pins=self.show_raw_pins)
        try:
            self.page.update()
        except Exception:
            pass

    def clear_logs_display(self) -> None:
        """Clears the table rows in the UI."""
        self.log_view.clear()
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

        self.user_view.update_rows(users, is_admin=self.is_admin)
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
        if self._periodic_logger:
            self._periodic_logger.stop()
        if self.serial_bridge:
            try:
                self.serial_bridge.stop()
            except Exception:
                pass
