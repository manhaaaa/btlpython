"""
data_analysis.py - Phân tích và trực quan hóa log hệ thống kiểm soát truy cập.

Đầu vào : access_control.db (bảng access_logs do Lộc xây dựng trong database.py)
          Cột: id, timestamp, event_type, status, detail
Đầu ra  : Charts/success_failed.png
          Charts/access_ratio.png
          Charts/access_time.png
          bao_cao_thong_ke.txt

Chạy:  python data_analysis.py
"""
import os
import sqlite3
import sys
import matplotlib
matplotlib.use("Agg")  # lưu ảnh, không cần mở cửa sổ
import matplotlib.pyplot as plt
import pandas as pd
DB_NAME = "access_control.db"
CHARTS_DIR = "Charts"
REPORT_PATH = "bao_cao_thong_ke.txt"
GREEN, RED, BLUE = "#2e9e5b", "#d64545", "#3b7dd8"

# Việc 1: Đọc dữ liệu từ access_control.db
def load_data():
    if not os.path.exists(DB_NAME):
        sys.exit(f"Không tìm thấy {DB_NAME}. Hãy đặt file cùng thư mục với script.")
    with sqlite3.connect(DB_NAME) as conn:
        df = pd.read_sql_query("SELECT * FROM access_logs ORDER BY id", conn)
    print(f"Đã đọc {len(df)} bản ghi từ bảng access_logs.")
    return df
# Việc 2: Xử lý, lọc dữ liệu bằng Pandas
def prepare(df):
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["event_type"] = df["event_type"].astype(str).str.strip().str.upper()
    df["status"] = df["status"].astype(str).str.strip().str.upper()
    bad = int(df["timestamp"].isna().sum())
    if bad:
        print(f"Cảnh báo: {bad} dòng có timestamp không hợp lệ (bị bỏ khi phân tích theo thời gian).")
    return df
def count(df, event_type, status=None):
    mask = df["event_type"] == event_type
    if status is not None:
        mask &= df["status"] == status
    return int(mask.sum())
# Việc 3, 4, 5, 6: Thống kê
def compute_stats(df):
    success = count(df, "ACCESS", "SUCCESS")
    failed = count(df, "ACCESS", "FAILED")
    attempts = success + failed
    valid = df.dropna(subset=["timestamp"])
    access = valid[valid["event_type"] == "ACCESS"]
    return {
        "total": len(df),
        "success": success,
        "failed": failed,
        "success_rate": success / attempts * 100 if attempts else 0.0,
        "failed_rate": failed / attempts * 100 if attempts else 0.0,
        "open": count(df, "DOOR", "OPEN"),
        "close": count(df, "DOOR", "CLOSE"),
        "alarm": count(df, "ALARM"),
        # Lượt truy cập (ACCESS) theo giờ và theo ngày, tách thành công / thất bại
        "by_hour": access.groupby([access["timestamp"].dt.hour, "status"])
        .size().unstack(fill_value=0)
        .reindex(range(24), fill_value=0)
        .reindex(columns=["SUCCESS", "FAILED"], fill_value=0),
        "by_day": access.groupby([access["timestamp"].dt.date, "status"])
        .size().unstack(fill_value=0)
        .reindex(columns=["SUCCESS", "FAILED"], fill_value=0),
    }
# Việc 7, 8: Vẽ biểu đồ bằng Matplotlib và lưu vào thư mục Charts
def draw_charts(s):
    os.makedirs(CHARTS_DIR, exist_ok=True)

    # 1) Thành công vs thất bại (cột)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    bars = ax.bar(["Thành công", "Thất bại"], [s["success"], s["failed"]], color=[GREEN, RED])
    ax.bar_label(bars, padding=3)
    ax.set_title("Số lượt truy cập thành công và thất bại")
    ax.set_ylabel("Số lượt")
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "success_failed.png"), dpi=150)
    plt.close(fig)

    # 2) Tỷ lệ (tròn)
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    if s["success"] + s["failed"] > 0:
        ax.pie([s["success"], s["failed"]], labels=["Thành công", "Thất bại"],
               colors=[GREEN, RED], autopct="%1.1f%%", startangle=90)
    ax.set_title("Tỷ lệ truy cập thành công / thất bại")
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "access_ratio.png"), dpi=150)
    plt.close(fig)

    # 3) Theo thời gian: theo giờ (trái), theo ngày (phải)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    h = s["by_hour"]
    ax1.bar(h.index, h["SUCCESS"], color=GREEN, label="Thành công")
    ax1.bar(h.index, h["FAILED"], bottom=h["SUCCESS"], color=RED, label="Thất bại")
    ax1.set_xticks(range(0, 24, 2))
    ax1.set_title("Lượt truy cập theo giờ trong ngày")
    ax1.set_xlabel("Giờ")
    ax1.set_ylabel("Số lượt")
    ax1.legend()
    d = s["by_day"]
    x = [str(i) for i in d.index]
    ax2.plot(x, d["SUCCESS"], marker="o", color=GREEN, label="Thành công")
    ax2.plot(x, d["FAILED"], marker="o", color=RED, label="Thất bại")
    ax2.set_title("Lượt truy cập theo ngày")
    ax2.set_xlabel("Ngày")
    ax2.tick_params(axis="x", rotation=45)
    ax2.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "access_time.png"), dpi=150)
    plt.close(fig)
# Việc 9: Kiểm tra độ chính xác - đếm lại bằng SQL thuần, so với Pandas
def verify(s):
    queries = [
        ("Thành công", s["success"],
         "SELECT COUNT(*) FROM access_logs WHERE event_type='ACCESS' AND status='SUCCESS'"),
        ("Thất bại", s["failed"],
         "SELECT COUNT(*) FROM access_logs WHERE event_type='ACCESS' AND status='FAILED'"),
        ("Mở cửa", s["open"],
         "SELECT COUNT(*) FROM access_logs WHERE event_type='DOOR' AND status='OPEN'"),
        ("Đóng cửa", s["close"],
         "SELECT COUNT(*) FROM access_logs WHERE event_type='DOOR' AND status='CLOSE'"),
        ("Báo động", s["alarm"],
         "SELECT COUNT(*) FROM access_logs WHERE event_type='ALARM'"),
    ]
    ok, lines = True, []
    with sqlite3.connect(DB_NAME) as conn:
        for name, pandas_v, sql in queries:
            sql_v = conn.execute(sql).fetchone()[0]
            match = pandas_v == sql_v
            ok &= match
            lines.append(f"   {name:<11} Pandas={pandas_v:<5} SQL={sql_v:<5} -> {'KHỚP' if match else 'LỆCH'}")
    rate = s["success_rate"] + s["failed_rate"]
    if s["success"] + s["failed"] > 0 and abs(rate - 100) > 1e-6:
        ok = False
    lines.append(f"   Tổng tỷ lệ thành công + thất bại = {rate:.2f}%")
    return ok, lines-
# Báo cáo
def write_report(s, ok, vlines):
    by_hour_total = s["by_hour"].sum(axis=1)
    peak = f"{int(by_hour_total.idxmax())}h" if by_hour_total.sum() > 0 else "không có dữ liệu"
    lines = [
        "BÁO CÁO PHÂN TÍCH HỆ THỐNG KIỂM SOÁT TRUY CẬP",
        "=" * 50,
        f"Tổng số bản ghi           : {s['total']}",
        "",
        "1. Kết quả truy cập",
        f"   Thành công             : {s['success']} ({s['success_rate']:.1f}%)",
        f"   Thất bại               : {s['failed']} ({s['failed_rate']:.1f}%)",
        "",
        "2. Số lần theo sự kiện",
        f"   Mở cửa                 : {s['open']}",
        f"   Đóng cửa               : {s['close']}",
        f"   Kích hoạt báo động     : {s['alarm']}",
        "",
        "3. Theo thời gian (lượt truy cập)",
        f"   Giờ cao điểm           : {peak}",
        f"   Số ngày có dữ liệu     : {len(s['by_day'])}",
        "",
        "4. Kiểm tra độ chính xác (Pandas so với SQL)",
        *vlines,
        f"   Kết luận               : {'ĐẠT' if ok else 'CÓ SAI LỆCH, CẦN KIỂM TRA LẠI'}",
        "",
        "Biểu đồ: Charts/success_failed.png, Charts/access_ratio.png, Charts/access_time.png",
    ]
    text = "\n".join(lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)
def main():
    df = prepare(load_data())
    stats = compute_stats(df)
    draw_charts(stats)
    ok, vlines = verify(stats)
    write_report(stats, ok, vlines)
    print(f"\nĐã lưu biểu đồ vào '{CHARTS_DIR}/' và báo cáo vào '{REPORT_PATH}'.")
if __name__ == "__main__":
    main()
