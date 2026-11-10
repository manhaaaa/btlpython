"""
Controls Bar UI Component: COM port selector, Reconnect, Refresh, Export, and Simulation controls.
"""
from typing import Callable, List, Optional
import flet as ft


class ControlsBarComponent:
    """Manages the interactive toolbar above the data tables."""

    def __init__(
        self,
        is_android: bool,
        current_port: str,
        available_ports: List[str],
        on_port_change: Callable[[ft.ControlEvent], None],
        on_reconnect: Callable[[ft.ControlEvent], None],
        on_refresh: Callable[[], None],
        on_clear: Callable[[], None],
        on_log_excel: Optional[Callable[[], None]] = None,
        on_sim_event: Optional[Callable[[str], None]] = None,
    ):
        self.is_android = is_android
        controls_items = []

        if not self.is_android:
            # Dropdown port selector
            ports = list(available_ports)
            for default_p in ["COM1", "COM2", "COM5", "COM6"]:
                if default_p not in ports:
                    ports.append(default_p)
            if current_port not in ports:
                ports.append(current_port)

            self.port_dropdown = ft.Dropdown(
                label="Cổng COM",
                value=current_port,
                options=[ft.dropdown.Option(p) for p in ports],
                width=130,
                dense=True,
                on_change=on_port_change,
            )

            self.connect_btn = ft.FilledButton(
                "Kết nối lại",
                icon=ft.Icons.SYNC,
                on_click=on_reconnect,
            )
            controls_items.extend([self.port_dropdown, self.connect_btn])
        else:
            # Android simulation event buttons
            btn_sim_success = ft.FilledButton(
                "Mô phỏng: Đúng PIN",
                icon=ft.Icons.CHECK_CIRCLE,
                bgcolor=ft.Colors.GREEN_700,
                on_click=lambda _: on_sim_event("SUCCESS") if on_sim_event else None,
            )
            btn_sim_fail = ft.FilledButton(
                "Mô phỏng: Sai PIN",
                icon=ft.Icons.CANCEL,
                bgcolor=ft.Colors.ORANGE_800,
                on_click=lambda _: on_sim_event("FAILED") if on_sim_event else None,
            )
            btn_sim_lock = ft.FilledButton(
                "Mô phỏng: Khóa tạm",
                icon=ft.Icons.WARNING,
                bgcolor=ft.Colors.RED_800,
                on_click=lambda _: on_sim_event("LOCKOUT") if on_sim_event else None,
            )
            controls_items.extend([btn_sim_success, btn_sim_fail, btn_sim_lock])

        btn_refresh = ft.OutlinedButton(
            "Làm mới",
            icon=ft.Icons.REFRESH,
            on_click=lambda _: on_refresh(),
        )
        btn_clear = ft.OutlinedButton(
            "Xóa hiển thị",
            icon=ft.Icons.CLEAR_ALL,
            on_click=lambda _: on_clear(),
        )
        controls_items.extend([btn_refresh, btn_clear])

        if on_log_excel:
            btn_export = ft.OutlinedButton(
                "Ghi Log Excel (30p)",
                icon=ft.Icons.TABLE_VIEW,
                tooltip="Ghi snapshot trạng thái hiện tại vào data/periodic_status_log.csv",
                on_click=lambda _: on_log_excel(),
            )
            controls_items.append(btn_export)

        self.card = ft.Card(
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
