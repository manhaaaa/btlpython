"""
Access Log Table UI Component.
Displays real-time access history with security masking (****) and optional Admin unmasking.
"""
from typing import Callable, List, Dict, Any
import flet as ft


class LogViewComponent:
    """Manages the Access Log Table and security masking switch."""

    def __init__(self, on_toggle_raw_pins: Callable[[ft.ControlEvent], None]):
        self.raw_pin_switch = ft.Switch(
            label="Hiện mã PIN thật các lần nhập trước",
            value=False,
            visible=False,
            on_change=on_toggle_raw_pins,
        )

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

        self.container = ft.Container(
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

    def update_rows(self, raw_logs: List[Dict[str, Any]], is_admin: bool, show_raw_pins: bool) -> None:
        """Renders the log entries with appropriate status coloring and PIN masking."""
        if is_admin and show_raw_pins:
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
            if is_admin and show_raw_pins:
                raw_pin_str = log.get("raw_pin", "")
                if not raw_pin_str and "PIN:" in log.get("detail", ""):
                    raw_pin_str = "****"
                cells.append(
                    ft.DataCell(
                        ft.Text(
                            raw_pin_str if raw_pin_str else "(Không rõ)",
                            color=ft.Colors.YELLOW_ACCENT,
                            weight=ft.FontWeight.BOLD,
                        )
                    )
                )

            rows.append(ft.DataRow(cells=cells))

        self.log_table.rows = rows

    def clear(self) -> None:
        """Clears displayed rows in the table."""
        self.log_table.rows.clear()
