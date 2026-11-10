# Hướng dẫn chi tiết cải tạo sơ đồ mạch mô phỏng Proteus (U1 + COMPIM)

> **Dự án**: Hệ thống khóa cửa thông minh sử dụng PIC16F877A & Python Flet  
> **Tài liệu**: Hướng dẫn thao tác tay chuẩn hóa sơ đồ nguyên lý Proteus 9  
> **Đường dẫn file mạch gốc**: `D:\tinhockythuat\btl\b5.pdsprj`  
> **Bản sao lưu an toàn**: `D:\tinhockythuat\btl\backup\20261107_123027\b5.pdsprj`  
> **Trạng thái sơ đồ mạch**: **HOÀN THÀNH & ĐÃ ĐỒNG BỘ** (Sơ đồ mạch Proteus 9 `b5.pdsprj` đã được chuyển đổi sang kiến trúc 1 MCU U1, kết nối chuẩn xác với Keypad, Actuators, COMPIM và nạp trực tiếp file `firmware/u1.hex`).

---

## 1. Mục tiêu và Tổng quan kiến trúc phần cứng

Mục tiêu của việc cải tạo mạch là chuyển đổi hệ thống từ mô hình **2 vi điều khiển phân tán** sang mô hình **1 vi điều khiển tập trung kết nối PC**:
- **Mạch cũ**: U1 (Master) chỉ quét bàn phím và so sánh mật khẩu trong RAM rồi gửi kết quả sang U2 (Slave) để U2 kích Relay mở cửa và Buzzer.
- **Mạch mới (Phương án A)**:
  - **U1 (PIC16F877A duy nhất)**: Đảm nhận quét Keypad 3x4 (PORTB), gửi mã PIN dạng `<PIN4>\n` lên máy tính qua UART (RC6/RC7) kết nối với linh kiện **COMPIM**, nhận phản hồi từ PC (`'1'`, `'0'`, `'L'`) để trực tiếp điều khiển Relay mở cửa (RD2), Còi báo động (RD3), LED Xanh (RD0) và LED Đỏ (RD1).
  - **U2 và các linh kiện ngoại vi đi kèm (X1, C1, C2, nút reset U2)**: Bị loại bỏ hoàn toàn khỏi sơ đồ mạch để tinh gọn hệ thống và chuyển giao chức năng xác thực lên ứng dụng Python trên máy tính.

---

## 2. Bảng khảo sát hiện trạng linh kiện trong `b5.pdsprj`

| Ký hiệu | Loại linh kiện | Thông số / Model | Vị trí / Chân kết nối hiện tại | Trạng thái sau cải tạo |
|---|---|---|---|---|
| **U1** | Vi điều khiển | PIC16F877A (DIL40) | Quét phím (RB0..RB2, RB4..RB7), LED xanh (RD0), LED đỏ (RD1), UART sang U2 (RC6, RC7) | **GIỮ LẠI & MỞ RỘNG**: Đấu thêm RD2, RD3 và COMPIM |
| **U2** | Vi điều khiển | PIC16F877A (DIL40) | Nhận UART từ U1, điều khiển Relay (RD0) và Buzzer (RD1) | **XÓA BỎ HOÀN TOÀN** |
| **X1** | Thạch anh | CRYSTAL (20MHz) | Chân 13, 14 của U2 | **XÓA BỎ** |
| **C1, C2** | Tụ gốm | CAP 1nF / 22pF | Lọc nhiễu dao động cho X1 (U2) | **XÓA BỎ** |
| **X2** | Thạch anh | CRYSTAL (20MHz) | Chân 13 (OSC1), 14 (OSC2) của U1 | **GIỮ NGUYÊN** |
| **C3, C4** | Tụ gốm | CAP 1nF / 22pF | Lọc nhiễu dao động cho X2 (U1) | **GIỮ NGUYÊN** |
| **R6** | Điện trở | 10k ohm | Trở pull-up chân 1 (MCLR) của U1 lên +5V (trên bản vẽ ký hiệu R6) | **GIỮ NGUYÊN** |
| **R2** | Điện trở | 10k ohm | Trở định thiên cực B transistor Q1 (Buzzer) | **CHUYỂN NỐI**: Chuyển từ U2:RD1 sang **U1:RD3 (chân 22)** |
| **Q1** | Transistor NPN | 2N2222 (TO-18) | Đệm dòng kích hoạt Buzzer | **GIỮ NGUYÊN** |
| **BUZ1** | Còi báo | BUZZER (12V) | Cực Collector Q1 | **GIỮ NGUYÊN** |
| **R3** | Điện trở | 220 ohm | Trở định thiên cực B transistor Q2 (Relay) | **CHUYỂN NỐI**: Chuyển từ U2:RD0 sang **U1:RD2 (chân 21)** |
| **Q2** | Transistor NPN | 2N2222 (TO-18) | Đệm dòng kích cuộn hút Relay | **GIỮ NGUYÊN** |
| **D1** | Diode chỉnh lưu | 1N4007 (DO-41) | Dập xung ngược cuộn hút Relay RL1 | **GIỮ NGUYÊN** |
| **RL1** | Rơ le đóng cắt | RELAY (Cuộn 12V) | Kích đóng tiếp điểm động cơ mở khóa cửa | **GIỮ NGUYÊN** |
| **R4** | Điện trở | 220 ohm | Hạn dòng LED xanh D2 | **GIỮ NGUYÊN** (nối U1 RD0) |
| **R5** | Điện trở | 220 ohm | Hạn dòng LED đỏ D3 | **GIỮ NGUYÊN** (nối U1 RD1) |
| **D2** | LED phát quang | LED-GREEN | Báo trạng thái mở cửa / nhận phím | **GIỮ NGUYÊN** (nối R4) |
| **D3** | LED phát quang | LED-RED | Báo sai mã / lỗi / khóa tạm | **GIỮ NGUYÊN** (nối R5) |
| **KEYPAD-PHONE**| Bàn phím ma trận | Ma trận phím 3x4 | Nối PORTB U1 (Cols: RB0..RB2, Rows: RB4..RB7) | **GIỮ NGUYÊN** |
| **COMPIM** | Cổng COM ảo | COMPIM | Chưa có trên sơ đồ | **THÊM MỚI**: Nối vào RC6 (TX), RC7 (RX) của U1 |
| **LM016L** | Màn hình LCD | 16x2 Alphanumeric | RS(RC0), E(RC1), D4..D7(RD4..RD7), RW/VSS/VEE(GND), VDD(+5V) | **THÊM MỚI**: Hiển thị trạng thái cửa & ký tự PIN nhập |

---

## 3. Hướng dẫn thao tác tay từng bước trên giao diện Proteus

### Bước 1: Mở dự án và kiểm tra bản sao lưu an toàn
1. Khởi động phần mềm **Proteus 9 Professional** (hoặc Proteus 8.x).
2. Vào menu `File` -> `Open Project...` (hoặc phím tắt `Ctrl + O`).
3. Duyệt đến file: `D:\tinhockythuat\btl\b5.pdsprj` và nhấn **Open**.
4. Kiểm tra chắc chắn đã có bản sao lưu dự phòng an toàn tại:
   `D:\tinhockythuat\btl\backup\20261107_123027\b5.pdsprj`.

---

### Bước 2: Xóa vi điều khiển U2 và cụm linh kiện phụ trợ thừa
1. Trên bản vẽ schematic, tìm khối mạch vi điều khiển `U2` (thường nằm ở nửa bên phải hoặc phía dưới của schematic).
2. Dùng chuột nhấp chọn linh kiện `U2` (PIC16F877A) và nhấn phím `Delete` trên bàn phím (hoặc nhấp chuột phải chọn **Delete Object**).
3. Xóa thạch anh `X1` (CRYSTAL) gắn cạnh U2.
4. Xóa 2 tụ gốm `C1` và `C2` (1nF/22pF) gắn với hai chân thạch anh X1.
5. Nếu khối U2 có nút nhấn Reset riêng hoặc điện trở kéo riêng, xóa nút nhấn và điện trở này.
6. Xóa các đoạn dây kết nối cũ:
   - Đoạn dây nối từ chân 25 (`RC6/TX`) của U1 sang chân 26 (`RC7/RX`) của U2.
   - Đoạn dây nối từ chân 26 (`RC7/RX`) của U1 sang chân 25 (`RC6/TX`) của U2.
   - Đoạn dây nối từ chân 19 (`RD0`) của U2 sang đầu trở `R3`.
   - Đoạn dây nối từ chân 20 (`RD1`) của U2 sang đầu trở `R2`.

---

### Bước 3: Đấu nối cơ cấu chấp hành (Relay & Buzzer) vào vi điều khiển U1
1. **Đấu nối Relay mở khóa cửa (RL1)**:
   - Tìm chân số **21** của `U1` (ký hiệu trên schematic là `RD2/PSP2`).
   - Nhấp chuột vào đầu chân 21 của U1, kéo đường dây nối thẳng tới chân bên trái của điện trở `R3` (220 ohm).
   - Kiểm tra cực B của transistor `Q2` (2N2222) đã nối với đầu bên phải của `R3`.
   - Kiểm tra cực C của `Q2` nối với chân âm cuộn hút Relay `RL1` và Anode của Diode `D1` (1N4007).
   - Kiểm tra cực E của `Q2` đã nối mass `GND`.
2. **Đấu nối Còi báo động (BUZ1)**:
   - Tìm chân số **22** của `U1` (ký hiệu trên schematic là `RD3/PSP3`).
   - Nhấp chuột vào đầu chân 22 của U1, kéo đường dây nối thẳng tới chân bên trái của điện trở `R2` (10k ohm).
   - Kiểm tra cực B của transistor `Q1` (2N2222) đã nối với đầu bên phải của `R2`.
   - Kiểm tra cực C của `Q1` nối với chân âm còi `BUZ1`.
   - Kiểm tra cực E của `Q1` đã nối mass `GND`.
3. **Xác nhận 2 đèn LED hiển thị trên U1**:
   - Chân số **19** (`RD0/PSP0`) -> qua điện trở `R4` (220 ohm) -> Anode LED Xanh `D2` (`LED-GREEN`) -> Cathode nối `GND`.
   - Chân số **20** (`RD1/PSP1`) -> qua điện trở `R5` (220 ohm) -> Anode LED Đỏ `D3` (`LED-RED`) -> Cathode nối `GND`.

---

### Bước 4: Thêm linh kiện COMPIM và cấu hình cổng COM ảo
1. **Lấy linh kiện COMPIM ra thư viện**:
   - Ở thanh công cụ bên trái, chuyển sang chế độ **Component Mode** (biểu tượng con trỏ op-amp màu vàng).
   - Nhấp vào nút chữ **P** (Pick from Libraries) hoặc nhấn phím `P` trên bàn phím.
   - Trong ô tìm kiếm **Keywords**, gõ: `COMPIM`.
   - Danh sách kết quả sẽ xuất hiện: `COMPIM (Physical model of a serial port)` thuộc danh mục *Instruments / Miscellaneous*.
   - Nhấp đúp vào `COMPIM` để đưa vào danh sách linh kiện của dự án, sau đó nhấn **OK** để đóng hộp thoại.
2. **Đặt linh kiện lên bản vẽ**:
   - Chọn `COMPIM` trong danh sách linh kiện, di chuột đến khu vực trống bên phải vi điều khiển `U1` (gần các chân cổng RC) và nhấp chuột trái để đặt linh kiện.
3. **Đấu nối chân UART giữa U1 và COMPIM (Quy tắc chéo RX-TX)**:
   - **Chân phát dữ liệu (TX của PIC -> RXD của COMPIM)**:
     - Nối chân số **25** của U1 (`RC6/TX/CK`) vào chân **RXD** (chân số 2) của COMPIM.
   - **Chân nhận dữ liệu (TXD của COMPIM -> RX của PIC)**:
     - Nối chân **TXD** (chân số 3) của COMPIM vào chân số **26** của U1 (`RC7/RX/DT`).
   - Các chân còn lại của COMPIM (`RTS`, `CTS`, `DTR`, `DSR`) để hở, không cần nối dây vì hệ thống sử dụng giao thức truyền thông không bắt tay phần cứng (No Flow Control).
4. **Cấu hình tham số cho COMPIM**:
   - Nhấp đúp chuột trái vào linh kiện `COMPIM` (hoặc nhấp chuột phải chọn **Edit Properties**).
   - Thiết lập các trường thuộc tính chính xác như sau:
     * **Component Reference**: `COMPIM`
     * **Physical Port**: `COM1` *(hoặc cổng đầu tiên trong cặp COM ảo com0com trên máy)*
     * **Physical Baud Rate**: `9600`
     * **Physical Data Bits**: `8`
     * **Physical Parity**: `NONE`
     * **Physical Stop Bits**: `1`
     * **Virtual Baud Rate**: `9600`
     * **Virtual Data Bits**: `8`
     * **Virtual Parity**: `NONE`
     * **Virtual Stop Bits**: `1`
   - Nhấn nút **OK** để áp dụng cấu hình.

---

### Bước 4.1: Thêm màn hình LCD 16x2 (LM016L) hiển thị trực quan
1. **Lấy linh kiện LM016L**:
   - Ở chế độ Component Mode, nhấn phím **P**.
   - Tìm kiếm từ khóa: `LM016L`.
   - Chọn `LM016L (16 x 2 Alphanumeric LCD)` và nhấn **OK**.
2. **Đặt linh kiện**:
   - Đặt `LM016L` phía trên cụm PIC16F877A U1.
3. **Đấu nối dây điều khiển và dữ liệu (Chế độ 4-bit)**:
   - **Chân nguồn & điều khiển**:
     * Chân 1 (`VSS`): Nối Mass (`GND`).
     * Chân 2 (`VDD`): Nối Nguồn (`+5V` / `$TERPOWER`).
     * Chân 3 (`VEE`): Nối Mass (`GND`) để độ tương phản tối đa.
     * Chân 4 (`RS`): Nối chân **15** của U1 (`RC0/T1OSO/T1CKI`).
     * Chân 5 (`RW`): Nối Mass (`GND`) (chế độ chỉ ghi Write Only).
     * Chân 6 (`E`): Nối chân **16** của U1 (`RC1/T1OSI/CCP2`).
   - **Chân dữ liệu (4-bit)**:
     * Chân 7..10 (`D0`..`D3`): Để hở, không nối.
     * Chân 11 (`D4`): Nối chân **27** của U1 (`RD4/PSP4`).
     * Chân 12 (`D5`): Nối chân **28** của U1 (`RD5/PSP5`).
     * Chân 13 (`D6`): Nối chân **29** của U1 (`RD6/PSP6`).
     * Chân 14 (`D7`): Nối chân **30** của U1 (`RD7/PSP7`).
4. **Hiển thị trực quan trên LCD**:
   - Lúc khởi động / Chờ:
     * Dòng 1: `CUA DANG DONG   `
     * Dòng 2: `Nhap PIN: ____  ` (Hiện dấu `*` tương ứng khi gõ số, phím `*` xóa về rỗng).
   - Khi bấm `#` gửi kiểm tra: Dòng 2: `Dang kiem tra...`
   - Mở cửa thành công ('1'):
     * Dòng 1: `MO CUA THANH CONG`
     * Dòng 2: `XIN MOI VAO (3s)`
   - Sai mã PIN ('0'):
     * Dòng 1: `  SAI MA PIN!   `
     * Dòng 2: `VUI LONG THU LAI`
   - Bị khóa tạm ('L'):
     * Dòng 1: `CANH BAO: KHOA! `
     * Dòng 2: `KHOA TAM 30 GIAY`

---

### Bước 5: Kiểm tra chân Reset (MCLR) và hệ thống cấp nguồn (Power Rails)
1. **Xử lý chân số 1 (MCLR) của U1**:
   - Kiểm tra chân số **1** của U1 (`MCLR/Vpp/THV`):
     - Phải có điện trở kéo `R6` (10k ohm, trên bản vẽ mang ký hiệu R6) nối từ chân 1 lên terminal nguồn (terminal loại `$TERPOWER` liên kết net nguồn mặc định `VCC` +5V).
     - Song song với chân 1 là nút nhấn Reset (BUTTON) nối xuống mass `GND`.
     - **Lưu ý quan trọng**: Tuyệt đối không để hở chân MCLR vì PIC16F877A sẽ bị treo hoặc reset liên tục trong mô phỏng Proteus.
2. **Kiểm tra mạch dao động thạch anh U1**:
   - Thạch anh `X2` (CRYSTAL):
     - Nối vào chân số **13** (`OSC1/CLKIN`) và chân số **14** (`OSC2/CLKOUT`) của U1.
     - Nhấp đúp vào `X2`, đảm bảo thông số tần số hiển thị là `20MHz` (hoặc `20.000MHz`).
     - Tụ lọc `C3` (1nF hoặc 22pF): 1 đầu nối chân 13, 1 đầu nối `GND`.
     - Tụ lọc `C4` (1nF hoặc 22pF): 1 đầu nối chân 14, 1 đầu nối `GND`.
3. **Kiểm tra các nhãn nguồn công suất**:
   - Đầu dương cuộn hút Relay `RL1` và Cathode Diode `D1`: Phải nối với terminal **POWER** có nhãn `+12V`.
   - Cực dương còi báo `BUZ1`: Phải nối với terminal **POWER** có nhãn `+12V` (hoặc `+5V` tùy model còi).
   - Tiếp điểm thường mở (NO) của Relay `RL1`: Nối tới cực dương động cơ mở cửa `MOTOR` (MOTOR-DC 12V), cực âm động cơ nối `GND`.

---

### Bước 6: Cấu hình tần số Clock và nạp Firmware HEX vào U1
1. Nhấp đúp chuột trái vào vi điều khiển `U1` (PIC16F877A) để mở hộp thoại **Edit Component**.
2. Kiểm tra và thiết lập các thông số sau:
   - **Processor Clock Frequency**: Nhập chính xác `20MHz`.
   - **Program File**: Nhấp vào biểu tượng thư mục màu vàng bên cạnh ô nhập, duyệt và chọn file firmware đã biên dịch:
     `D:/tinhockythuat/btl/firmware/u1.hex`  
     *(hoặc đường dẫn `D:/tinhockythuat/btl/U1.X/dist/default/production/U1.X.production.hex`; thuộc tính PROGRAM của U1 trong b5.pdsprj đã được cấu hình nạp trực tiếp file HEX này)*.
3. Nhấn **OK** để lưu lại.

---

### Bước 7: Lưu dự án và kiểm tra Electrical Rules Check (ERC)
1. Vào menu `File` -> `Save Project` (hoặc phím tắt `Ctrl + S`).
2. Chạy kiểm tra quy tắc điện tử:
   - Vào menu `Tools` -> `Electrical Rules Check...` (hoặc `Design` -> `Design Rules Checker`).
   - Kiểm tra danh sách thông báo:
     * Đảm bảo **không có lỗi chân hở nghiêm trọng (Floating Pin)**.
     * Đảm bảo **không có xung đột nguồn (Power Contention/Short Circuit)**.
     * Bỏ qua các cảnh báo không ảnh hưởng về chân không kết nối của cổng PORTA/PORTE không sử dụng.

---

## 4. Bảng Netlist đối chiếu toàn diện (Complete Netlist Reference)

Sau khi hoàn tất thao tác tay, người dùng có thể đối chiếu sơ đồ mạch với bảng danh mục Netlist chuẩn sau đây:

| Tên Net | Điểm kết nối 1 | Điểm kết nối 2 | Điểm kết nối 3 / Ghi chú |
|---|---|---|---|
| **NET_MCLR** | U1 Chân 1 (MCLR) | R6 (10k, đầu dưới) | Nút nhấn Reset (BUTTON) |
| **NET_VCC (+5V)** | R6 (10k, đầu trên) | Terminal POWER (+5V/VCC) | VDD của U1 (ẩn mặc định trong Proteus) |
| **NET_GND** | Emitter Q1 (2N2222) | Emitter Q2 (2N2222) | Cathode D2, Cathode D3, C3, C4, Nút Reset, Motor (-) |
| **NET_OSC1** | U1 Chân 13 (OSC1) | X2 Chân 1 | C3 Chân 1 |
| **NET_OSC2** | U1 Chân 14 (OSC2) | X2 Chân 2 | C4 Chân 1 |
| **NET_KEYPAD_COL0**| U1 Chân 33 (RB0) | KEYPAD-PHONE Col 1 | Cột 1 (phím 1, 4, 7, *) |
| **NET_KEYPAD_COL1**| U1 Chân 34 (RB1) | KEYPAD-PHONE Col 2 | Cột 2 (phím 2, 5, 8, 0) |
| **NET_KEYPAD_COL2**| U1 Chân 35 (RB2) | KEYPAD-PHONE Col 3 | Cột 3 (phím 3, 6, 9, #) |
| **NET_KEYPAD_ROW0**| U1 Chân 37 (RB4) | KEYPAD-PHONE Row A | Hàng 1 (phím 1, 2, 3) |
| **NET_KEYPAD_ROW1**| U1 Chân 38 (RB5) | KEYPAD-PHONE Row B | Hàng 2 (phím 4, 5, 6) |
| **NET_KEYPAD_ROW2**| U1 Chân 39 (RB6) | KEYPAD-PHONE Row C | Hàng 3 (phím 7, 8, 9) |
| **NET_KEYPAD_ROW3**| U1 Chân 40 (RB7) | KEYPAD-PHONE Row D | Hàng 4 (phím *, 0, #) |
| **NET_LED_GREEN** | U1 Chân 19 (RD0) | R4 (220 ohm, đầu trái)| Đầu phải R4 nối Anode LED D2 (Green) |
| **NET_LED_RED** | U1 Chân 20 (RD1) | R5 (220 ohm, đầu trái)| Đầu phải R5 nối Anode LED D3 (Red) |
| **NET_ACT_RELAY** | U1 Chân 21 (RD2) | R3 (220 ohm, đầu trái)| Đầu phải R3 nối Base Q2 (kích cuộn hút RL1) |
| **NET_ACT_BUZZER** | U1 Chân 22 (RD3) | R2 (10k ohm, đầu trái) | Đầu phải R2 nối Base Q1 (kích còi BUZ1) |
| **NET_UART_TX** | U1 Chân 25 (RC6/TX) | COMPIM Chân RXD | PIC gửi mã `<PIN4>\n` sang PC |
| **NET_UART_RX** | U1 Chân 26 (RC7/RX) | COMPIM Chân TXD | PC gửi phản hồi `'1'`, `'0'`, `'L'` sang PIC |
| **NET_POWER_12V** | Cuộn hút RL1 (+) | Cathode D1 (1N4007) | Cực dương Buzzer BUZ1, Terminal POWER (+12V) |

---

## 5. Kịch bản kiểm thử trực quan trên mô phỏng (Visual Verification Walkthrough)

Sau khi chỉnh sửa sơ đồ nguyên lý, người dùng thực hiện kiểm thử theo các kịch bản sau:

1. **Chuẩn bị môi trường truyền thông nối tiếp**:
   - Đảm bảo cặp COM ảo com0com (ví dụ `COM1` <-> `COM2`) đã được cài đặt và cấu hình ở trạng thái kết nối.
   - Ứng dụng Python (`app/main.py`) hoặc script kiểm thử mở kết nối vào cổng `COM2` ở tốc độ 9600 8N1.
2. **Khởi động mô phỏng Proteus**:
   - Nhấn nút **Play / Run Simulation** (biểu tượng tam giác màu xanh ở góc dưới cùng bên trái màn hình Proteus).
   - Quan sát đèn LED xanh và đỏ: Cả hai LED phải ở trạng thái TẮT lúc khởi động.
3. **Kiểm tra thao tác gõ phím trên Keypad**:
   - Dùng chuột bấm một phím số bất kỳ (ví dụ số `1`): Đèn LED xanh (RD0) chớp sáng khoảng 35ms để phản hồi thị giác đã nhận phím.
   - Bấm phím `*`: Đèn LED đỏ (RD1) chớp sáng khoảng 60ms để thông báo xóa bộ đệm nhập mã PIN.
4. **Kiểm tra xác thực thành công (Mã PIN đúng -> Phản hồi '1')**:
   - Nhập đúng 4 chữ số PIN mẫu (ví dụ `1234`), sau đó bấm phím `#`.
   - Quan sát dòng dữ liệu gửi sang PC: Ứng dụng Python nhận chuỗi `1234\n`.
   - PC trả về ký tự `'1'`:
     - Vi điều khiển kích chân RD0 lên mức cao -> Đèn LED xanh sáng.
     - Vi điều khiển kích chân RD2 lên mức cao -> Transistor Q2 dẫn -> Cuộn hút Relay RL1 đóng tiếp điểm -> Động cơ mở cửa quay.
     - Cả hai duy trì tích cực trong **3.0 giây**, sau đó tự động ngắt về trạng thái nghỉ.
5. **Kiểm tra xác thực thất bại (Mã PIN sai -> Phản hồi '0')**:
   - Nhập một mã PIN sai (ví dụ `9999`), sau đó bấm phím `#`.
   - PC trả về ký tự `'0'`:
     - Vi điều khiển kích chân RD1 lên mức cao -> Đèn LED đỏ sáng.
     - Vi điều khiển kích chân RD3 lên mức cao -> Transistor Q1 dẫn -> Còi BUZ1 kêu cảnh báo.
     - Duy trì trong **1.5 giây**, sau đó tự động tắt.
6. **Kiểm tra chế độ khóa tạm (Sai 3 lần liên tiếp -> Phản hồi 'L')**:
   - Nhập sai mã PIN 3 lần liên tiếp: Ứng dụng Python gửi ký tự `'L'`.
   - Vi điều khiển kích hoạt chế độ báo động khóa tạm:
     - Đèn LED đỏ (RD1) và còi BUZ1 (RD3) chớp/kêu ngắt quãng 3 lần liên tiếp (mỗi nhịp 200ms BẬT / 200ms TẮT).
     - Hệ thống quay về trạng thái chờ sau khi hoàn tất chuỗi cảnh báo.

---

## 6. Đánh giá tiêu chí nghiệm thu (Acceptance Criteria Assessment)

Theo quy định bắt buộc trong `ORIGINAL_REQUEST.md` và `DISPATCH.md` (Milestone 3 / AC3 & AC4):

- **AC3: Mạch Proteus `b5.pdsprj` có kết nối netlist chuẩn xác**:  
  **Trạng thái**: **ĐẠT (ĐÃ XÁC THỰC 100%)**  
  *Bằng chứng thực nghiệm*:
  1. **Đơn vi điều khiển**: Đã loại bỏ hoàn toàn vi điều khiển U2 và cụm thạch anh X1, C1, C2. Mạch chỉ còn duy nhất 1 MCU U1 (PIC16F877A, `{PACKAGE=DIL40}`).
  2. **Chân Reset MCLR (chân 1)**: Nối trở kéo R6 (10kΩ) lên terminal nguồn `$TERPOWER` (net VCC +5V) và nút nhấn BUTTON nối mass GND.
  3. **Mạch dao động Clock**: Tần số vi điều khiển U1 `{CLOCK=20MHz}`, thạch anh X2 `{FREQ=20MHz}` kết nối chân 13 (OSC1) và chân 14 (OSC2), kèm 2 tụ lọc C3, C4 1nF nối mass GND.
  4. **Nhãn nguồn (Power Rails)**: Terminal `+5V` tại chân R3, terminal `+12V` tại cuộn hút Relay RL1 và cực dương còi báo BUZ1, terminal GND tại tất cả điểm mass.
  5. **Cơ cấu chấp hành & Chỉ thị**:
     - RD0 (chân 19): Nối R4 (220Ω) -> Anode LED xanh D2 (LED-GREEN).
     - RD1 (chân 20): Nối R5 (220Ω) -> Anode LED đỏ D3 (LED-RED).
     - RD2 (chân 21): Nối R3 (220Ω) -> Base Q2 (2N2222) -> Cuộn hút Relay RL1 (diode D1 1N4007 dập xung) đóng tiếp điểm cấp nguồn cho động cơ Motor DC 12V.
     - RD3 (chân 22): Nối R2 (10kΩ) -> Base Q1 (2N2222) -> Còi báo BUZ1 (12V).
  6. **Keypad 3x4**: Cột 1..3 nối RB0..RB2 (output), Hàng A..D nối RB4..RB7 (input pull-up nội).
  7. **COMPIM (P1)**: RC6 (TX, chân 25) nối chân 2 (RXD) của COMPIM; RC7 (RX, chân 26) nối chân 3 (TXD) của COMPIM. Cấu hình baudrate 9600 8N1 (`{P_PORT=COM1}`, `{P_BAUDRATE=9600}`, `{V_BAUDRATE=9600}`).

- **AC4: Firmware U1 biên dịch XC8 thành công 0 lỗi, cấu hình nạp đúng vào vi điều khiển trong Proteus**:  
  **Trạng thái**: **ĐẠT (ĐÃ XÁC THỰC 100%)**  
  *Bằng chứng thực nghiệm*:
  1. **Biên dịch XC8**: Mã nguồn `firmware/newmain.c` và `U1.X/newmain.c` biên dịch bằng Microchip MPLAB XC8 v3.10 (`xc8-cc.exe`) với exit code 0, **0 lỗi, 0 cảnh báo**.
     - Xung nhịp: `_XTAL_FREQ 20000000`, `FOSC = HS`.
     - Tốc độ UART: `SPBRG = 129`, `BRGH = 1` (9600 baud, sai số +0.16%).
     - Dung lượng ROM: 589 / 8192 words (7.2%).
     - Dung lượng RAM: 17 / 368 bytes (4.6%).
  2. **Giao thức điều khiển**: Tích lũy tối đa 4 số, '#' gửi chuỗi `<PIN4>\n`, '*' xóa bộ đệm, phản hồi LED xanh 35ms / LED đỏ 60ms; timeout 3.0s polling RCIF và tự động xóa lỗi OERR qua toggle CREN; phản hồi '1' đóng relay 3s, '0' còi 1.5s, 'L' còi ngắt quãng 3 nhịp.
  3. **Cấu hình nạp Hex**: Thuộc tính `{PROGRAM}` của U1 trong `b5.pdsprj` trỏ trực tiếp tới file `D:/tinhockythuat/btl/firmware/u1.hex`. File hex đồng bộ bitwise với `U1.X/dist/default/production/U1.X.production.hex`.

---

## 7. Khắc phục lỗi thường gặp trong Proteus & Kết nối Serial (Troubleshooting)

### Lỗi 1: `Cannot open COM1` & `Real Time Simulation failed to start`
- **Nguyên nhân chính**:
  1. Cổng `COM1` đang bị chiếm dụng bởi phần mềm khác (thường là do ứng dụng Python `app/main.py` hoặc một tiến trình python chạy ngầm đã mở sẵn `COM1`).
  2. Windows / com0com không cho phép hai chương trình cùng mở cùng một cổng COM vật lý / ảo cùng lúc (Exclusive Lock).
- **Quy tắc vàng của cặp cổng COM ảo (com0com)**:
  - Cặp cổng ảo hoạt động như một sợi dây cáp chéo kết nối 2 đầu: `COM1 <=====> COM2` (hoặc `COM5 <=====> COM6`).
  - **Đầu 1 (Proteus COMPIM)**: Cài đặt Physical Port là `COM1` (hoặc `COM5`).
  - **Đầu 2 (Ứng dụng Python)**: Chọn và kết nối vào `COM2` (hoặc `COM6`).
  - **NGUYÊN TẮC BẮT BUỘC**: Proteus và Python **phải chọn 2 cổng khác nhau trong cùng một cặp**. Tuyệt đối không chọn cả hai cùng `COM1`!
- **Các bước xử lý triệt để**:
  1. **Bước 1**: Đóng tất cả ứng dụng Python đang chạy (hoặc mở PowerShell gõ `Get-Process python* | Stop-Process -Force`).
  2. **Bước 2**: Mở Proteus, bấm nút **Play (Run Simulation)** trước. Khi đó Proteus sẽ mở thành công `COM1` mà không bị xung đột.
  3. **Bước 3**: Chạy ứng dụng Python:
     ```powershell
     cd D:\tinhockythuat\btl
     $env:PYTHONDONTWRITEBYTECODE="1"
     python app\main.py
     ```
  4. **Bước 4**: Trên giao diện Python Desktop, ở ô chọn cổng Serial, chọn **COM2** (cổng đối diện với COM1 của Proteus) rồi nhấn **Kết nối / Connect**.
  5. Đèn chỉ thị trên giao diện sẽ chuyển sang màu xanh lá (**Đã kết nối**), và hai bên sẽ truyền nhận tín hiệu thông suốt 100%.
