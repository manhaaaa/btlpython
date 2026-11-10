"""
User Management UI Component: Users DataTable, Admin Login Box, and Admin Control Panel.
"""
from typing import Callable, List, Dict, Any, Optional
import flet as ft


class UserManagementComponent:
    """Manages User Profiles, Admin Privileges, and Account Configuration."""

    def __init__(
        self,
        current_port: str,
        master_pin_val: str,
        on_admin_login: Callable[[ft.ControlEvent], None],
        on_save_master_pin: Callable[[ft.ControlEvent], None],
        on_save_com_port: Callable[[ft.ControlEvent], None],
        on_add_user: Callable[[ft.ControlEvent], None],
        on_edit_user_pin: Callable[[str, str], None],
        on_delete_user: Callable[[str], None],
    ):
        self.on_edit_user_pin = on_edit_user_pin
        self.on_delete_user = on_delete_user

        # Admin Control Panel Inputs
        self.master_pin_input = ft.TextField(
            label="Mật khẩu chính cố định (Master PIN)",
            value=master_pin_val,
            width=220,
            dense=True,
        )
        self.admin_port_input = ft.TextField(
            label="Cổng COM (VD: COM1, COM2...)",
            value=current_port,
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
                                ft.Text(
                                    "BẢNG ĐIỀU KHIỂN DÀNH CHO QUẢN TRỊ VIÊN",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.AMBER,
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Divider(),
                        # Section 1: Master PIN & COM Port
                        ft.Row(
                            [
                                self.master_pin_input,
                                ft.FilledButton("Lưu Master PIN", icon=ft.Icons.VPN_KEY, on_click=on_save_master_pin),
                                ft.Container(width=16),
                                self.admin_port_input,
                                ft.FilledButton("Lưu Cổng COM", icon=ft.Icons.SAVE, on_click=on_save_com_port),
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
                                ft.FilledButton(
                                    "Thêm Người Dùng",
                                    icon=ft.Icons.PERSON_ADD,
                                    bgcolor=ft.Colors.GREEN_800,
                                    on_click=on_add_user,
                                ),
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

        # Admin Login Box
        self.login_user_input = ft.TextField(label="Tên tài khoản", value="admin", width=160, dense=True)
        self.login_pass_input = ft.TextField(
            label="Mật khẩu",
            value="1234",
            password=True,
            can_reveal_password=True,
            width=160,
            dense=True,
        )
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
                        ft.FilledButton(
                            "Đăng Nhập",
                            icon=ft.Icons.LOGIN,
                            bgcolor=ft.Colors.BLUE_800,
                            on_click=on_admin_login,
                        ),
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

        self.container = ft.Container(
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

    def set_admin_mode(self, is_admin: bool) -> None:
        """Toggles UI visibility between Admin mode and standard User mode."""
        self.admin_controls_panel.visible = is_admin
        self.admin_login_box.visible = not is_admin

    def update_rows(self, users: List[Dict[str, Any]], is_admin: bool) -> None:
        """Renders registered user accounts."""
        rows = []
        for u in users:
            uid = str(u.get("id", ""))
            uname = str(u.get("name", ""))
            role = u.get("role", "user")
            role_color = ft.Colors.LIGHT_BLUE if role == "admin" else ft.Colors.WHITE_70
            pin_str = str(u.get("pin", "****"))

            if is_admin:
                action_control = ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.EDIT,
                            tooltip=f"Đổi PIN cho {uname}",
                            icon_color=ft.Colors.AMBER,
                            on_click=lambda _, i=uid, n=uname: self.on_edit_user_pin(i, n),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip=f"Xóa {uname}",
                            icon_color=ft.Colors.RED_400,
                            on_click=lambda _, i=uid: self.on_delete_user(i),
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
                        ft.DataCell(
                            ft.Text(
                                pin_str,
                                color=ft.Colors.GREEN_ACCENT if is_admin else ft.Colors.WHITE_54,
                                weight=ft.FontWeight.BOLD if is_admin else ft.FontWeight.NORMAL,
                            )
                        ),
                        ft.DataCell(action_control),
                    ]
                )
            )

        self.users_table.rows = rows
