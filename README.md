# Hệ Thống Khóa Cửa Thông Minh Xác Thực Mã PIN (Smart PIN Door Lock System)

> Dự án bài tập lớn môn học & Showcase trình diễn: Hệ thống khóa cửa bảo mật tích hợp vi điều khiển **PIC16F877A (U1)**, mô phỏng **Proteus**, kết nối hai chiều qua **UART / Virtual COM** với Backend **Python 3.11**, ứng dụng giao diện đa nền tảng **Flet** (Windows Desktop & Android APK), cùng quy trình CI/CD tự động qua **GitHub Actions**.

---

## Mục lục

1. [Tổng quan dự án & Kiến trúc hệ thống](#1-tổng-quan-dự-án--kiến-trúc-hệ-thống)
2. [Sơ đồ nguyên lý & Sơ đồ chân vi điều khiển PIC16F877A](#2-sơ-đồ-nguyên-lý--sơ-đồ-chân-vi-điều-khiển-pic16f877a)
3. [Giao thức truyền thông UART ASCII & Cơ chế bảo mật](#3-giao-thức-truyền-thông-uart-ascii--cơ-chế-bảo-mật)
4. [Hướng dẫn cài đặt & Chạy ứng dụng trên Windows Desktop](#4-hướng-dẫn-cài-đặt--chạy-ứng-dụng-trên-windows-desktop)
5. [Giới hạn & Chế độ Demo trên Android APK](#5-giới-hạn--chế-độ-demo-trên-android-apk)
6. [Hướng dẫn cấu hình cổng COM ảo com0com kết nối Proteus](#6-hướng-dẫn-cấu-hình-cổng-com-ảo-com0com-kết-nối-proteus)
7. [Kiểm thử độc lập không cần Proteus](#7-kiểm-thử-độc-lập-không-cần-proteus)
8. [Quy trình CI/CD GitHub Actions & Đóng gói APK](#8-quy-trình-cicd-github-actions--đóng-gói-apk)
9. [Cấu trúc mã nguồn dự án](#9-cấu-trúc-mã-nguồn-dự-án)
10. [Hướng dẫn đẩy mã nguồn lên GitHub (Git Push Guide)](#10-hướng-dẫn-đẩy-mã-nguồn-lên-github-git-push-guide)

---

## 1. Tổng quan dự án & Kiến trúc hệ thống

Hệ thống được thiết kế theo mô hình 3 tầng phân tán an toàn và tin cậy:

```
+-----------------------------------------------------------------------------------------+
|                               TẦNG PHẦN CỨNG & MÔ PHỎNG                                 |
|                                                                                         |
|  +-------------------+        +--------------------+        +------------------------+  |
|  | Keypad Ma trận 3x4| -----> | PIC16F877A (U1)    | -----> | LED Xanh (RD0)         |  |
|  | (PORTB: RB0..RB7) |        | - XC8 @ 20MHz      |        | LED Đỏ (RD1)           |  |
|  +-------------------+        | - Quét mã PIN 4 số |        | Relay Motor Cửa (RD2)  |  |
|                               | - Timeout 3.0s     |        | Buzzer Báo động (RD3)  |  |
|                               +---------+----------+        +------------------------+  |
|                                         |                                               |
|                                         | Chân RC6 (TX), RC7 (RX)                       |
|                                         v                                               |
|                               +--------------------+                                    |
|                               | Linh kiện COMPIM   |                                    |
|                               | (Proteus COM1)     |                                    |
+-------------------------------+---------+----------+------------------------------------+
                                          |
                      Virtual COM Pair (com0com: COM1 <-> COM2)
                                          |
+-----------------------------------------v-----------------------------------------------+
|                            TẦNG BACKEND & XÁC THỰC PYTHON                               |
|                                                                                         |
|  +-----------------------------------------------------------------------------------+  |
|  | Module Serial Bridge (app/serial_bridge.py)                                       |  |
|  | - pyserial kết nối COM2, tự động reconnect khi mất kết nối                         |  |
|  | - Lọc định dạng mã PIN qua Regex ^\d{4}$ (loại bỏ chuỗi rác)                      |  |
|  | - Cơ chế đếm lỗi: Sai 3 lần liên tiếp -> Kích hoạt Khóa tạm (30s) -> Phản hồi 'L'  |  |
|  +------------------------------------------+----------------------------------------+  |
|                                             |                                           |
|  +------------------------------------------v----------------------------------------+  |
|  | Module Dịch vụ Xác thực (app/auth_service.py)                                     |  |
|  | - Kiểm tra mã PIN đa người dùng (app/users.json)                                  |  |
|  | - Tích hợp ghi nhật ký hệ thống qua data.database.save_log()                      |  |
|  | - Bảo vệ dữ liệu: PYTHONDONTWRITEBYTECODE=1, mã PIN che giấu thành '****'         |  |
|  +-----------------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------------+
                                          |
+-----------------------------------------v-----------------------------------------------+
|                               TẦNG GIAO DIỆN NGƯỜI DÙNG                                 |
|                                                                                         |
|  +----------------------------------+            +-----------------------------------+  |
|  | Windows Desktop (Flet Desktop)   |            | Android APK (Flet Mobile App)     |  |
|  | - Kết nối cổng COM thực tế       |            | - Tự động nhận diện Android       |  |
|  | - Điều khiển đóng/mở/khóa trực quan|          | - Chế độ Giám sát/Demo mô phỏng   |  |
|  | - Bảng nhật ký thời gian thực    |            | - Không dùng pyserial hay data/   |  |
|  +----------------------------------+            +-----------------------------------+  |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Sơ đồ nguyên lý & Sơ đồ chân vi điều khiển PIC16F877A

Hệ thống đã được tối ưu hóa toàn diện, loại bỏ vi điều khiển phụ U2 thừa, thạch anh X1, tụ C1/C2 và nút reset cũ. Toàn bộ tính năng quét phím, hiển thị, giao tiếp máy tính và chấp hành được tích hợp vào vi điều khiển **PIC16F877A (U1)**.

### 2.1 Bảng phân bổ chân vi điều khiển U1

| Chân PIC | Tên Port | Hướng I/O | Linh kiện kết nối | Chức năng kỹ thuật |
| :--- | :--- | :--- | :--- | :--- |
| **Pin 1** | `MCLR/VPP` | Input | Điện trở kéo lên 10kΩ lên +5V | Chân Reset phần cứng, giữ mức cao ổn định chống sụt áp. |
| **Pin 13, 14**| `OSC1, OSC2` | I/O | Thạch anh X2 (20MHz) + 2x tụ 22pF | Tạo xung nhịp dao động chính 20MHz cho vi điều khiển (FOSC=HS). |
| **Pin 25** | `RC6/TX` | Output | Chân `RXD` của linh kiện COMPIM | Truyền dữ liệu UART ASCII sang máy tính (Baud 9600, 8N1). |
| **Pin 26** | `RC7/RX` | Input | Chân `TXD` của linh kiện COMPIM | Nhận tín hiệu điều khiển UART ASCII từ máy tính. |
| **Pin 33** | `RB0` | Output | Cột 1 (Col 1) Bàn phím ma trận 3x4 | Quét ma trận phím (xuất xung mức thấp lần lượt). |
| **Pin 34** | `RB1` | Output | Cột 2 (Col 2) Bàn phím ma trận 3x4 | Quét ma trận phím. |
| **Pin 35** | `RB2` | Output | Cột 3 (Col 3) Bàn phím ma trận 3x4 | Quét ma trận phím. |
| **Pin 37** | `RB4` | Input | Hàng 1 (Row 1) Bàn phím ma trận 3x4 | Đọc phím hàng 1 (sử dụng weak pull-up nội `nRBPU=0`). |
| **Pin 38** | `RB5` | Input | Hàng 2 (Row 2) Bàn phím ma trận 3x4 | Đọc phím hàng 2 (weak pull-up nội). |
| **Pin 39** | `RB6` | Input | Hàng 3 (Row 3) Bàn phím ma trận 3x4 | Đọc phím hàng 3 (weak pull-up nội). |
| **Pin 40** | `RB7` | Input | Hàng 4 (Row 4) Bàn phím ma trận 3x4 | Đọc phím hàng 4 (weak pull-up nội). |
| **Pin 19** | `RD0` | Output | Cực Anode LED Xanh D2 qua trở hạn dòng | Bật mức cao (5V) báo hiệu xác thực thành công. |
| **Pin 20** | `RD1` | Output | Cực Anode LED Đỏ D3 qua trở hạn dòng | Bật mức cao (5V) báo hiệu sai mã PIN, khóa tạm hoặc timeout. |
| **Pin 21** | `RD2` | Output | Điện trở R3 -> Cực B Transistor NPN Q2 | Kích hoạt Relay RL1 điều khiển động cơ chốt cửa (+12V). |
| **Pin 22** | `RD3` | Output | Điện trở R2 -> Cực B Transistor NPN Q1 | Kích hoạt Còi Buzzer BUZ1 báo động âm thanh (+5V). |

### 2.2 Sơ đồ khối nguyên lý nguồn & tải
- **Đường nguồn logic (+5V)**: Cấp cho chân VDD của vi điều khiển PIC, còi Buzzer, và điện trở pull-up chân MCLR.
- **Đường nguồn công suất (+12V)**: Cấp cho cuộn hút Relay RL1 và động cơ chốt cửa.
- **Diode dập tia lửa điện ngược (Flyback Diode D1)**: Mắc song song ngược chiều với cuộn dây Relay RL1 để bảo vệ transistor Q2 khi ngắt dòng cảm ứng.

---

## 3. Giao thức truyền thông UART ASCII & Cơ chế bảo mật

### 3.1 Cấu hình thông số vật lý
- **Baud Rate**: `9600 bps` (Cấu hình thanh ghi PIC: `SPBRG = 129`, `BRGH = 1` với FOSC = 20MHz).
- **Data Bits**: `8`
- **Parity**: `None`
- **Stop Bits**: `1` (8N1)
- **Flow Control**: `None`

### 3.2 Quy trình nhập phím trên bàn phím ma trận
1. Người dùng nhập lần lượt từng ký tự số `0` - `9`.
2. Khi đã nhập đủ 4 chữ số, việc nhấn thêm bất kỳ phím số nào khác sẽ bị **bỏ qua**.
3. Nhấn phím `#`: Xác nhận chuỗi mã PIN (khi đã đủ 4 số), vi điều khiển gửi chuỗi sang PC.
4. Nhấn phím `*`: Xóa trắng bộ đệm nhập liệu, đưa hệ thống về trạng thái sẵn sàng nhập lại từ đầu.

### 3.3 Định dạng gói tin gửi từ PIC -> Máy tính
Chuỗi ASCII đúng 4 ký tự số kèm ký tự xuống dòng `\n`:
$$\text{Gói tin} = \langle\text{PIN}_4\rangle\backslash\text{n} \quad (\text{Ví dụ: } \texttt{"1234\textbackslash n"}, \texttt{"5678\textbackslash n"})$$

### 3.4 Phản hồi từ Máy tính -> PIC (1 ký tự ASCII duy nhất)
Sau khi nhận và xử lý xác thực, phần mềm trên máy tính gửi lại 1 ký tự:

| Ký tự nhận | Trạng thái xác thực | Hành vi của vi điều khiển PIC16F877A U1 |
| :---: | :--- | :--- |
| **`'1'`** | **Hợp lệ (Access Granted)** | Bật đồng thời **LED Xanh (RD0)** và kích hoạt **Relay mở cửa (RD2)** trong **3.0 giây**, sau đó tự động tắt hết. |
| **`'0'`** | **Sai mã PIN (Access Denied)** | Bật đồng thời **LED Đỏ (RD1)** và phát **Còi Buzzer (RD3)** trong **1.5 giây**, sau đó tắt. |
| **`'L'`** | **Khóa tạm (Lockout Alarm)** | **LED Đỏ (RD1)** nhấp nháy và **Còi Buzzer (RD3)** kêu ngắt quãng **3 lần** (chu kỳ 200ms BẬT / 200ms TẮT). |

*Lưu ý*: Trong thời gian vi điều khiển đang thực thi các hiệu ứng chấp hành (3.0s mở cửa hoặc 1.5s còi hoặc chuỗi cảnh báo khóa), mọi thao tác nhấn phím trên ma trận bàn phím đều bị vô hiệu hóa để chống xung đột và tránh nghẽn luồng.

### 3.5 Cơ chế chống treo (Timeout) & Phục hồi lỗi UART
- Vi điều khiển PIC thăm dò cờ nhận `RCIF` với thời gian chờ tối đa **3.0 giây**.
- Nếu máy tính không phản hồi trong vòng 3.0s (do mất kết nối hoặc cáp lỏng), hoặc nếu phần cứng UART gặp lỗi tràn bộ đệm (`OERR`) hoặc lỗi khung (`FERR`), vi điều khiển tự động:
  1. Xóa bit lỗi bằng cách tắt và bật lại cờ `CREN` (`RCSTAbits.CREN = 0; RCSTAbits.CREN = 1;`).
  2. Nháy LED Đỏ (RD1) **2 lần** để cảnh báo người dùng.
  3. Xóa bộ đệm và quay trở lại trạng thái đón nhận thao tác nhập phím mới.

### 3.6 Cơ chế Khóa tạm (Temporary Lockout) tại tầng Backend
- Module `app/serial_bridge.py` lọc dữ liệu thô nhận được từ cổng COM bằng biểu thức chính quy:
  $$\text{Regex: } \texttt{r'\text{\textasciicircum}}\backslash\text{d}\{4\}\$'\text{ (sau khi strip ký tự \textbackslash r\textbackslash n)}$$
  Dữ liệu rác không đúng chuẩn sẽ bị bỏ qua và ghi log cảnh báo.
- Bộ đếm theo dõi số lần xác thực sai liên tiếp:
  - Khi người dùng nhập sai mã PIN **3 lần liên tiếp**, hệ thống tự động kích hoạt chế độ **Khóa tạm** trong khoảng thời gian cấu hình (mặc định **30 giây**, có thể cấu hình **5 giây** để kiểm thử nhanh).
  - Trong suốt thời gian khóa, mọi mã PIN gửi lên đều lập tức nhận phản hồi `'L'`.
  - Khi hết thời gian khóa, bộ đếm lỗi được reset về 0 và hệ thống tự động mở lại cho người dùng thử tiếp.
- Mọi sự kiện đều được ghi vào nhật ký hệ thống qua hàm an toàn của thư viện `data.database`, với mã PIN tuyệt đối không lưu thô mà luôn được che giấu thành `****`.

---

## 4. Hướng dẫn cài đặt & Chạy ứng dụng trên Windows Desktop

### 4.1 Yêu cầu hệ thống
- Hệ điều hành: Windows 10 hoặc Windows 11 (64-bit).
- Python: Phiên bản **3.11.x** (khuyến nghị Python 3.11.9).
- Bộ công cụ mô phỏng: Proteus 8 / Proteus 9 (mở file mạch `b5.pdsprj`).
- Phần mềm cổng COM ảo: **com0com** (xem hướng dẫn ở Mục 6).

### 4.2 Các bước cài đặt môi trường
1. Mở cửa sổ dòng lệnh PowerShell tại thư mục dự án `D:\tinhockythuat\btl`:
   ```powershell
   cd D:\tinhockythuat\btl
   ```
2. Cài đặt các thư viện phụ thuộc dành cho bản Desktop:
   ```powershell
   pip install -r requirements-desktop.txt
   ```

### 4.3 Cấu hình thông số kết nối
Kiểm tra và tùy chỉnh file `app/config.json`:
```json
{
  "port": "COM2",
  "baudrate": 9600,
  "timeout": 1.0,
  "lockout_threshold": 3,
  "lockout_duration_seconds": 30,
  "test_lockout_duration_seconds": 5
}
```

### 4.4 Khởi chạy ứng dụng
Chạy ứng dụng giao diện Flet Desktop:
```powershell
python -m app.main
```
Hoặc sử dụng Flet CLI nếu đã cài đặt:
```powershell
flet run app/main.py
```

### 4.5 Tính năng giao diện Desktop
- **Trạng thái kết nối COM**: Hiển thị trạng thái kết nối thời gian thực (`ĐÃ KẾT NỐI (COM2)`, `MẤT KẾT NỐI`, `ĐANG KẾT NỐI LẠI...`).
- **Trạng thái cửa thông minh**:
  - `CỬA ĐÓNG`: Màu xanh dương nhã nhặn khi hệ thống ở trạng thái chờ.
  - `CỬA MỞ`: Màu xanh lá cây nổi bật khi nhập đúng mã PIN (kèm đếm ngược thời gian mở chốt).
  - `HỆ THỐNG KHÓA TẠM`: Màu đỏ cảnh báo khi nhập sai 3 lần, hiển thị thời gian còn lại trước khi mở khóa.
- **Bảng Nhật ký ra vào thời gian thực**:
  - Liệt kê các cột: `Thời gian`, `Người dùng`, `Sự kiện`, `Trạng thái`, `Chi tiết`.
  - Toàn bộ mã PIN được bảo vệ nghiêm ngặt bằng mặt nạ `****`.
- **Khả năng chịu lỗi cao**: Tự động phục hồi kết nối nền khi cổng COM bị ngắt hoặc Proteus khởi động lại, giao diện hoàn toàn không bị gián đoạn hay treo ứng dụng.

---

## 5. Giới hạn & Chế độ Demo trên Android APK

### 5.1 Giới hạn kỹ thuật của nền tảng Android
1. **Không hỗ trợ RS-232 / pyserial tiêu chuẩn**: Nền tảng Android chạy trong môi trường sandbox với quyền hạn bảo mật nghiêm ngặt và không cung cấp giao tiếp cổng Serial COM tiêu chuẩn như trên máy tính xách tay / PC. Thư viện native `pyserial` không tương thích và sẽ gây lỗi crash nếu được import trên Android.
2. **Bảo mật cơ sở dữ liệu nội bộ**: Thư mục dữ liệu gốc `data/` chứa các thông tin cục bộ và không được phép đóng gói vào gói cài đặt công khai APK.

### 5.2 Cơ chế tách biệt kiến trúc trên Android
- **Tự động nhận diện nền tảng**: Ứng dụng Flet tự kiểm tra môi trường chạy (`page.platform == ft.PagePlatform.ANDROID` hoặc biến môi trường `FLET_PLATFORM`).
- **Chế độ Giám sát & Mô phỏng (Monitor / Demo Mode)**:
  - Tự động ẩn hoàn toàn các bảng điều khiển cổng COM vật lý.
  - Tuyệt đối **KHÔNG import `pyserial`**, **KHÔNG import `auth_service`**, và **KHÔNG truy cập `data/`**.
  - Sử dụng module dữ liệu độc lập `app/demo_data.py` để hiển thị danh sách người dùng mẫu và mô phỏng các sự kiện mở cửa/báo động phục vụ trình diễn và thuyết trình dự án.
- **Cấu hình đóng gói `pyproject.toml` chuẩn hóa**: File cấu hình gói APK ở gốc repo chỉ phụ thuộc vào `flet`, tuyệt đối loại trừ `pyserial` để đảm bảo quá trình build APK diễn ra hoàn toàn tự động và sạch sẽ.

---

## 6. Hướng dẫn cấu hình cổng COM ảo com0com kết nối Proteus

Để phần mềm Proteus và Python có thể trao đổi dữ liệu UART với nhau trên cùng một máy tính, cần sử dụng cặp cổng COM ảo liên kết chéo qua phần mềm **Null-modem emulator (com0com)**.

### 6.1 Cài đặt com0com
1. Tải bộ cài com0com (phiên bản hỗ trợ signed driver cho Windows x64, ví dụ `com0com-3.0.0.0-i386-and-x64-signed.zip`).
2. Chạy file cài đặt với quyền quản trị viên (**Run as Administrator**).
3. Cho phép cài đặt driver khi Windows UAC hiển thị thông báo.

### 6.2 Tạo cặp cổng ảo COM1 <-> COM2
1. Mở công cụ cấu hình **Setup Command Prompt** của com0com (Run as Administrator) hoặc công cụ đồ họa `setupg.exe`.
2. Tạo hoặc đổi tên cặp cổng mặc định (`CNCA0` và `CNCB0`) thành `COM1` và `COM2`:
   ```cmd
   install PortName=COM1 PortName=COM2
   ```
3. Bật cờ cho phép tràn bộ đệm (Buffer Overrun):
   ```cmd
   change CNCA0 EmuBR=yes
   change CNCB0 EmuBR=yes
   ```
4. Kiểm tra trong `Device Manager` -> Mục `Ports (COM & LPT)` xuất hiện hai cổng `com0com - serial port emulator (COM1)` và `com0com - serial port emulator (COM2)`.

### 6.3 Cấu hình linh kiện COMPIM trong Proteus
1. Mở file mạch nguyên lý `b5.pdsprj` trong Proteus.
2. Tìm linh kiện **COMPIM** (đã được nối chân `RXD -> RC6` và `TXD -> RC7` của vi điều khiển U1).
3. Nhấp đúp chuột trái vào linh kiện COMPIM để mở hộp thoại thuộc tính:
   - **Physical port**: Chọn `COM1`
   - **Physical Baud Rate**: Chọn `9600`
   - **Physical Data Bits**: Chọn `8`
   - **Physical Parity**: Chọn `NONE`
   - **Physical Stop Bits**: Chọn `1`
   - **Virtual Baud Rate**: Chọn `9600`
   - **Virtual Data Bits**: Chọn `8`
   - **Virtual Parity**: Chọn `NONE`
   - **Virtual Stop Bits**: Chọn `1`
4. Nhấn **OK** để lưu lại cấu hình.
5. Nạp file firmware đã biên dịch `firmware/u1.hex` vào vi điều khiển PIC16F877A U1 (đặt xung nhịp Processor Clock = `20MHz`).
6. Nhấn nút **Play** ở góc trái phía dưới của Proteus để bắt đầu mô phỏng.

---

## 7. Kiểm thử độc lập không cần Proteus

Hệ thống được trang bị bộ kiểm thử tự động độc lập hoàn chỉnh, cho phép xác minh 100% logic giao thức UART, xác thực mã PIN, cơ chế khóa tạm 5s/30s và bảo vệ dữ liệu mà không phụ thuộc vào giao diện Proteus:

```powershell
python tests/test_serial_mock.py
```

### Các kịch bản kiểm thử bao gồm:
1. **Kiểm tra PIN đúng**: Gửi `1234\n` -> Nhận phản hồi `'1'`, ghi log thành công.
2. **Kiểm tra PIN sai**: Gửi `0000\n` -> Nhận phản hồi `'0'`, tăng bộ đếm lỗi.
3. **Kiểm tra Lọc dữ liệu rác**: Gửi `abc\n`, `12345\n`, chuỗi ký tự đặc biệt -> Backend bỏ qua và ghi log cảnh báo an toàn.
4. **Kiểm tra Khóa tạm 5 giây (Quick Lockout Test)**: Nhập sai 3 lần liên tiếp -> Nhận phản hồi `'L'`, kiểm tra mở khóa tự động sau 5s.
5. **Kiểm tra Khóa tạm 30 giây thực tế (Standard Lockout Test)**: Xác minh thời gian khóa an toàn thực tế đạt đúng 30 giây theo tiêu chuẩn bảo mật.
6. **Kiểm tra Mặt nạ PIN**: Xác minh toàn bộ nhật ký ghi nhận mã PIN dưới dạng `****`.

---

## 8. Quy trình CI/CD GitHub Actions & Đóng gói APK

Dự án tích hợp sẵn quy trình CI/CD tự động thông qua GitHub Actions tại đường dẫn:
`.github/workflows/build-apk.yml`

### 8.1 Luồng hoạt động của Workflow
- **Trigger**: Tự động kích hoạt khi có sự kiện `push` hoặc `pull_request` vào nhánh `main` / `master`, hoặc có thể kích hoạt thủ công bằng nút `Run workflow` (`workflow_dispatch`).
- **Môi trường thực thi**: `ubuntu-latest`.
- **Các bước thực hiện**:
  1. `actions/checkout@v4`: Tải toàn bộ mã nguồn của dự án.
  2. `actions/setup-java@v4`: Thiết lập môi trường Java 17 Temurin.
  3. `subosito/flutter-action@v2`: Cài đặt môi trường Flutter ổn định (`stable`).
  4. `actions/setup-python@v5`: Thiết lập môi trường Python 3.11.
  5. Cài đặt các thư viện cần thiết: `pip install flet`.
  6. Thực thi lệnh đóng gói: `flet build apk --project . --verbose`.
  7. `actions/upload-artifact@v4`: Tải file `build/apk/*.apk` lên mục Artifacts của GitHub.

### 8.2 Tải file APK thành phẩm
1. Truy cập vào kho mã nguồn trên GitHub.
2. Chuyển sang tab **Actions**.
3. Chọn bản chạy workflow mới nhất vừa hoàn thành (biểu tượng tích xanh).
4. Cuộn xuống mục **Artifacts** ở dưới trang và tải gói `door-access-control-apk`.

---

## 9. Cấu trúc mã nguồn dự án

```
D:\tinhockythuat\btl\
├── .github/
│   └── workflows/
│       └── build-apk.yml            # CI/CD Workflow tự động build Android APK
├── app/
│   ├── __init__.py                  # Đóng gói package app
│   ├── auth_service.py              # Dịch vụ xác thực đa người dùng & tích hợp data.database
│   ├── config.json                  # Cấu hình cổng COM, baudrate, thời gian khóa tạm
│   ├── demo_data.py                 # Bộ dữ liệu mô phỏng & người dùng demo cho Android
│   ├── main.py                      # Giao diện Flet đa nền tảng (Desktop & Android)
│   ├── serial_bridge.py             # Giao tiếp pyserial, regex filter, auto-reconnect, lockout
│   └── users.json                   # Danh sách tài khoản người dùng và mã PIN bảo mật
├── backup/                          # Thư mục sao lưu nguyên vẹn (được gitignore bảo vệ)
│   └── 20261107_123027/             # Bản sao lưu gốc của data, b5.pdsprj, newmain.c
├── data/                            # THƯ MỤC DỮ LIỆU GỐC ĐƯỢC BẢO VỆ CHỈ ĐỌC
│   ├── access_control.db            # Cơ sở dữ liệu SQLite lịch sử truy cập (được gitignore bảo vệ)
│   ├── access_logs.csv              # File xuất nhật ký CSV
│   ├── bao_cao_thong_ke.txt         # Báo cáo thống kê
│   ├── database.py                  # Module API thao tác cơ sở dữ liệu gốc
│   ├── data_analysis.py             # Module phân tích số liệu
│   └── Charts/                      # Biểu đồ phân tích trực quan
├── docs/
│   └── proteus_steps.md             # Hướng dẫn chi tiết từng bước cải tạo sơ đồ Proteus
├── firmware/
│   ├── newmain.c                    # Mã nguồn C cho PIC16F877A U1 (XC8 Compiler)
│   └── u1.hex                       # File mã máy Intel HEX nạp vào vi điều khiển U1
├── tests/
│   └── test_serial_mock.py          # Script kiểm thử độc lập mô phỏng loopback & khóa tạm
├── .gitignore                       # Cấu hình loại trừ file nhạy cảm, DB, cache, build
├── b5.pdsprj                        # File thiết kế sơ đồ nguyên lý mạch mô phỏng Proteus
├── pyproject.toml                   # File cấu hình Flet đóng gói APK (chỉ chứa flet)
├── README.md                        # Tài liệu hướng dẫn toàn diện bằng Tiếng Việt
└── requirements-desktop.txt         # Thư viện phụ thuộc khi chạy trên máy tính Windows
```

---

## 10. Hướng dẫn đẩy mã nguồn lên GitHub (Git Push Guide)

Vì máy tính hiện tại chưa đăng nhập GitHub CLI (`gh`), người dùng có thể dễ dàng khởi tạo kho mã nguồn từ xa (Remote Repository) và đẩy toàn bộ mã nguồn lên GitHub theo các câu lệnh chi tiết dưới đây:

### Bước 1: Tạo một Repository mới trên GitHub
1. Đăng nhập vào tài khoản cá nhân tại [GitHub](https://github.com).
2. Nhấn vào biểu tượng **`+`** ở góc trên bên phải -> Chọn **New repository**.
3. Điền tên Repository (ví dụ: `smart-pin-door-lock`).
4. Chọn chế độ bảo mật **Private** (khuyến nghị) hoặc **Public**.
5. **Không** tích chọn *"Add a README file"*, *"Add .gitignore"* hay *"Choose a license"* (vì các file này đã được tạo sẵn trong dự án).
6. Nhấn nút **Create repository**.

### Bước 2: Liên kết Remote và Đẩy mã nguồn từ máy tính
Mở cửa sổ dòng lệnh PowerShell tại thư mục dự án `D:\tinhockythuat\btl` và thực thi:

```powershell
# Chuyển vào thư mục dự án
cd D:\tinhockythuat\btl

# Đổi tên nhánh mặc định thành main (nếu đang ở master)
git branch -M main

# Thêm địa chỉ kho lưu trữ từ xa (thay thế URL bằng đường dẫn repo của bạn)
git remote add origin https://github.com/<tai-khoan-cua-ban>/smart-pin-door-lock.git

# Đẩy toàn bộ mã nguồn và lịch sử commit lên nhánh main
git push -u origin main
```

*(Sau khi push thành công, hệ thống GitHub Actions sẽ tự động nhận diện file `.github/workflows/build-apk.yml` và tiến hành quy trình kiểm tra, build APK tự động).*
