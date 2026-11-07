import tkinter as tk
from tkinter import ttk, messagebox
from queue import Queue, Empty
import threading

from database import create_database, save_log, get_logs, export_csv
from data_analysis import analyze_data

EVENTS = {
    "ACCESS_OK": ("ACCESS", "SUCCESS", "Truy cập thành công - cho phép mở cửa"),
    "ACCESS_FAIL": ("ACCESS", "FAILED", "Truy cập thất bại - sai mật khẩu/thẻ"),
    "DOOR_OPEN": ("DOOR", "OPEN", "Cửa đang mở"),
    "DOOR_CLOSE": ("DOOR", "CLOSED", "Cửa đã đóng"),
    "ALARM": ("SECURITY", "WARNING", "Cảnh báo an ninh"),
    "SYSTEM_READY": ("SYSTEM", "READY", "Hệ thống đã sẵn sàng")
}

class App:
    def __init__(self, root):
        self.root = root
        root.title("HE THONG KIEM SOAT TRUY CAP - PIC16F877A")
        root.geometry("1050x650")
        self.serial = None
        self.running = True
        self.queue = Queue()
        self.build_ui()
        self.refresh()
        root.after(150, self.read_queue)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def build_ui(self):
        tk.Label(self.root, text="HỆ THỐNG KIỂM SOÁT TRUY CẬP VÀ GIÁM SÁT",
                 font=("Arial", 17, "bold"), fg="#17365D").pack(pady=12)

        com = ttk.LabelFrame(self.root, text="Kết nối cổng COM (tùy chọn)")
        com.pack(fill="x", padx=12, pady=5)
        ttk.Label(com, text="Cổng COM:").pack(side="left", padx=(10, 3), pady=8)
        self.port = ttk.Entry(com, width=10)
        self.port.insert(0, "COM4")
        self.port.pack(side="left")
        ttk.Label(com, text="Baud:").pack(side="left", padx=(12, 3))
        self.baud = ttk.Entry(com, width=8)
        self.baud.insert(0, "9600")
        self.baud.pack(side="left")
        ttk.Button(com, text="Kết nối", command=self.connect).pack(side="left", padx=8)
        ttk.Button(com, text="Ngắt kết nối", command=self.disconnect).pack(side="left")
        self.com_status = tk.StringVar(value="Chưa kết nối - đang ở chế độ chạy thử")
        ttk.Label(com, textvariable=self.com_status).pack(side="left", padx=12)

        demo = ttk.LabelFrame(self.root, text="Mô phỏng sự kiện (chưa cần Proteus)")
        demo.pack(fill="x", padx=12, pady=6)
        buttons = [
            ("Truy cập đúng", "ACCESS_OK"), ("Truy cập sai", "ACCESS_FAIL"),
            ("Mở cửa", "DOOR_OPEN"), ("Đóng cửa", "DOOR_CLOSE"),
            ("Báo động", "ALARM"), ("Sẵn sàng", "SYSTEM_READY")
        ]
        for label, code in buttons:
            ttk.Button(demo, text=label, command=lambda c=code: self.event(c)).pack(
                side="left", padx=5, pady=9, expand=True, fill="x")

        self.status = tk.StringVar(value="Đang chờ sự kiện...")
        ttk.Label(self.root, textvariable=self.status, font=("Arial", 11, "bold")).pack(pady=7)

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", padx=12, pady=4)
        ttk.Button(actions, text="Làm mới", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(actions, text="Xuất CSV", command=self.export).pack(side="left", padx=4)
        ttk.Button(actions, text="Phân tích và vẽ biểu đồ", command=self.analysis).pack(side="left", padx=4)

        frame = ttk.LabelFrame(self.root, text="Lịch sử sự kiện")
        frame.pack(fill="both", expand=True, padx=12, pady=8)
        cols = ("id", "timestamp", "event_type", "status", "detail")
        self.table = ttk.Treeview(frame, columns=cols, show="headings")
        titles = ("ID", "Thời gian", "Loại sự kiện", "Trạng thái", "Chi tiết")
        widths = (55, 165, 145, 125, 430)
        for col, title, width in zip(cols, titles, widths):
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w" if col == "detail" else "center")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        tk.Label(self.root, text="Dữ liệu được lưu trong SQLite; biểu đồ được tạo bằng Pandas và Matplotlib.",
                 fg="#555").pack(pady=5)

    def event(self, code):
        event_type, status, detail = EVENTS[code]
        save_log(event_type, status, detail)
        self.status.set(f"{code}: {detail}")
        self.refresh()

    def refresh(self):
        for item in self.table.get_children():
            self.table.delete(item)
        df = get_logs(limit=300)
        for _, row in df.iterrows():
            self.table.insert("", "end", values=(
                row["id"], row["timestamp"], row["event_type"], row["status"], row["detail"]))

    def export(self):
        try:
            path = export_csv()
            messagebox.showinfo("Xuất CSV", f"Đã xuất file:\n{path}")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def analysis(self):
        try:
            result = analyze_data(show_charts=True)
            if result["total"] == 0:
                messagebox.showinfo("Phân tích", result["message"])
            else:
                messagebox.showinfo("Kết quả",
                    f'{result["message"]}\n\nTổng lượt: {result["total"]}'
                    f'\nThành công: {result["success"]} ({result["success_rate"]:.1f}%)'
                    f'\nThất bại: {result["failed"]} ({result["failed_rate"]:.1f}%)')
        except Exception as e:
            messagebox.showerror("Lỗi phân tích", str(e))

    def connect(self):
        if self.serial is not None:
            return
        try:
            import serial
            self.serial = serial.Serial(self.port.get().strip(), int(self.baud.get()), timeout=1)
            threading.Thread(target=self.serial_reader, daemon=True).start()
            self.com_status.set("Đã kết nối " + self.port.get().strip())
        except ImportError:
            messagebox.showerror("Thiếu thư viện", "Chạy lệnh: python -m pip install pyserial")
        except Exception as e:
            self.serial = None
            messagebox.showerror("Lỗi COM", str(e))

    def serial_reader(self):
        while self.running and self.serial is not None:
            try:
                line = self.serial.readline()
                if line:
                    code = line.decode("utf-8", errors="ignore").strip()
                    if code:
                        self.queue.put(code)
            except Exception:
                break

    def read_queue(self):
        try:
            while True:
                code = self.queue.get_nowait()
                if code in EVENTS:
                    self.event(code)
                else:
                    self.status.set("Mã UART chưa được khai báo: " + code)
        except Empty:
            pass
        if self.running:
            self.root.after(150, self.read_queue)

    def disconnect(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None
        self.com_status.set("Đã ngắt kết nối COM")

    def close(self):
        self.running = False
        self.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    create_database()
    root = tk.Tk()
    App(root)
    root.mainloop()
