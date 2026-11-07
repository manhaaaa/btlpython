from pathlib import Path
import matplotlib.pyplot as plt
from database import get_logs

CHART_DIR = Path(__file__).with_name("Charts")

def analyze_data(show_charts=True):
    CHART_DIR.mkdir(exist_ok=True)
    df = get_logs()
    if df.empty:
        return {"message": "Chưa có dữ liệu. Hãy tạo sự kiện thử nghiệm trước.", "total": 0}

    df["timestamp"] = __import__("pandas").to_datetime(df["timestamp"], errors="coerce")
    access = df[df["event_type"] == "ACCESS"].copy()
    success = int((access["status"] == "SUCCESS").sum())
    failed = int((access["status"] == "FAILED").sum())
    total = success + failed
    if total == 0:
        return {"message": "Chưa có sự kiện truy cập thành công/thất bại.", "total": 0}

    # Biểu đồ cột: số lượt thành công và thất bại
    fig, ax = plt.subplots()
    ax.bar(["Thanh cong", "That bai"], [success, failed])
    ax.set_title("Thong ke truy cap")
    ax.set_ylabel("So luot")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "success_failed.png", dpi=150)
    if show_charts: plt.show()
    plt.close(fig)

    # Biểu đồ tròn: tỷ lệ truy cập
    fig, ax = plt.subplots()
    ax.pie([success, failed], labels=["Thanh cong", "That bai"],
           autopct="%1.1f%%", startangle=90)
    ax.set_title("Ty le truy cap")
    fig.tight_layout()
    fig.savefig(CHART_DIR / "access_ratio.png", dpi=150)
    if show_charts: plt.show()
    plt.close(fig)

    # Biểu đồ đường: số lượt truy cập theo giờ
    access = access.dropna(subset=["timestamp"])
    access["hour"] = access["timestamp"].dt.hour
    hourly = access.groupby("hour").size().reindex(range(24), fill_value=0)
    fig, ax = plt.subplots()
    ax.plot(hourly.index, hourly.values, marker="o")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Gio trong ngay")
    ax.set_ylabel("So luot")
    ax.set_title("Luot truy cap theo gio")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "access_time.png", dpi=150)
    if show_charts: plt.show()
    plt.close(fig)

    return {"message": "Đã lưu 3 biểu đồ trong thư mục Charts.",
            "total": total, "success": success, "failed": failed,
            "success_rate": success / total * 100,
            "failed_rate": failed / total * 100}

if __name__ == "__main__":
    print(analyze_data())
