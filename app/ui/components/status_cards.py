"""
Status Cards UI Components: Door Status Card & Serial Connection Card.
"""
import flet as ft


class StatusCardsComponent:
    """Manages the real-time visual indicators for Door State and Serial Connection."""

    def __init__(self, is_android: bool = False, initial_port: str = "COM6"):
        self.is_android = is_android

        # Door Status Card Controls
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

        # Serial Connection Card Controls
        if not self.is_android:
            self.serial_icon = ft.Icon(ft.Icons.CABLE, size=48, color=ft.Colors.RED)
            self.serial_label = ft.Text("MẤT KẾT NỐI", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED)
            self.serial_desc = ft.Text(f"Cổng COM: {initial_port} | Baud: 9600 8N1", size=12, color=ft.Colors.WHITE_60)
            title = "KẾT NỐI SERIAL COMPIM"
        else:
            self.serial_icon = ft.Icon(ft.Icons.PHONE_ANDROID, size=48, color=ft.Colors.CYAN)
            self.serial_label = ft.Text("CHẾ ĐỘ DEMO", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN)
            self.serial_desc = ft.Text("Độc lập phần cứng | Không yêu cầu PySerial", size=12, color=ft.Colors.WHITE_60)
            title = "NỀN TẢNG ANDROID"

        self.serial_card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        self.serial_icon,
                        ft.Column(
                            [
                                ft.Text(title, size=11, color=ft.Colors.WHITE_54, weight=ft.FontWeight.BOLD),
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

        self.cards_row = ft.Row([self.door_card, self.serial_card], spacing=16)

    def update_door(self, door_state: str, detail: str = "") -> None:
        """Updates door visual controls based on door state."""
        if door_state == "OPEN":
            self.door_icon.name = ft.Icons.LOCK_OPEN
            self.door_icon.color = ft.Colors.GREEN
            self.door_label.value = "CỬA ĐANG MỞ"
            self.door_label.color = ft.Colors.GREEN
            self.door_desc.value = detail or "Mở khóa thành công (Relay kích hoạt)"
        elif door_state == "LOCKED":
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

    def update_serial(self, serial_state: str, port: str = "COM6") -> None:
        """Updates serial visual controls based on connection state."""
        if self.is_android:
            return

        if serial_state in ("CONNECTED", "PIC_READY"):
            self.serial_icon.name = ft.Icons.CABLE
            self.serial_icon.color = ft.Colors.GREEN
            self.serial_label.value = "ĐÃ KẾT NỐI PIC"
            self.serial_label.color = ft.Colors.GREEN
            self.serial_desc.value = f"Cổng {port} đang mở | PIC16F877A sẵn sàng (9600 8N1)"
        elif serial_state in ("PORT_OPEN", "LISTENING"):
            self.serial_icon.name = ft.Icons.SYNC
            self.serial_icon.color = ft.Colors.AMBER
            self.serial_label.value = "CHỜ TÍN HIỆU PIC"
            self.serial_label.color = ft.Colors.AMBER
            self.serial_desc.value = f"Cổng {port} đã mở - Đang đợi PIC phản hồi..."
        elif serial_state == "RECONNECTING":
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
