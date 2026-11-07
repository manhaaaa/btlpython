# Bản demo hệ thống kiểm soát truy cập

## Cài đặt
Mở PowerShell tại thư mục này:
```powershell
python -m pip install pandas matplotlib pyserial
```
Tkinter và sqlite3 thường có sẵn trong Python Windows.

## Chạy chương trình
```powershell
python main.py
```

## Chạy thử không cần Proteus
Nhấn các nút Truy cập đúng, Truy cập sai, Mở cửa, Đóng cửa, Báo động, Sẵn sàng.
Sự kiện sẽ được lưu vào `access_control.db` và hiện trong bảng.

- `Xuất CSV`: tạo file `access_logs.csv`.
- `Phân tích và vẽ biểu đồ`: thống kê thành công/thất bại và tạo 3 ảnh trong `Charts`.

## Kết nối Proteus/PIC qua COM ảo
Tạo một cặp cổng COM ảo, ví dụ COM3-COM4. Proteus dùng một đầu, Python dùng đầu còn lại.
Nhập cổng Python (ví dụ COM4), baud rate 9600, rồi bấm Kết nối.
PIC cần gửi từng mã sự kiện kết thúc bằng newline:
- ACCESS_OK
- ACCESS_FAIL
- DOOR_OPEN
- DOOR_CLOSE
- ALARM
- SYSTEM_READY

Tên COM chỉ là ví dụ, hãy dùng đúng cặp cổng trên máy. Giao thức phải thống nhất với firmware PIC.
