import sqlite3
from datetime import datetime
DB_NAME="access_control.db"   #Khai bao ten CSDL
# 1. Tao co so du lieu va bang access_logs
def create_database():
    conn=sqlite3.connect(DB_NAME)
    cursor=conn.cursor()  #cursor la doi tuong de thuc hien cac cau lenh SQL.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (    
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL,
        detail TEXT
    )
""")   #Day la cau lenh SQL de tao bang access_logs.
    conn.commit() #luu nhung thay doi vao CSDL
    conn.close()  #dong ket noi sau khi hoan thanh cong viec
    print("Da tao co so du lieu thanh cong!")
# 2. Luu mot su kien vao co so du lieu
def save_log(event_type, status, detail=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO access_logs
        (timestamp, event_type, status, detail)
        VALUES (?, ?, ?, ?) 
    """, (timestamp, event_type, status, detail))
    conn.commit()
    conn.close()
    print("Da luu nhat ky thanh cong!")
# 3. Doc danh sach nhat ky
def get_logs(limit=None):  #ham doc nhat ky, limit la so luong ban ghi muon lay ra
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if limit is None:
        cursor.execute("""
            SELECT * FROM access_logs
            ORDER BY id DESC
        """)
    else:
        cursor.execute("""
            SELECT * FROM access_logs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
    logs = cursor.fetchall()
    conn.close()
    return logs
# 4. Loc nhat ky theo dieu kien
def filter_logs(event_type=None, status=None,
                start_time=None, end_time=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql = "SELECT * FROM access_logs WHERE 1=1"
    params = []
    if event_type is not None:
        sql += " AND event_type = ?"
        params.append(event_type)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if start_time is not None:
        sql += " AND timestamp >= ?"
        params.append(start_time)
    if end_time is not None:
        sql += " AND timestamp <= ?"
        params.append(end_time)
    sql += " ORDER BY id DESC"
    cursor.execute(sql, params)
    logs = cursor.fetchall()
    conn.close()
    return logs
# 5. Xuat du lieu ra file CSV
def export_csv():
    import csv
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM access_logs
        ORDER BY id
    """)
    logs = cursor.fetchall()
    with open("access_logs.csv", "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "id", "timestamp", "event_type", "status", "detail"
        ])
        writer.writerows(logs)
    conn.close()
    print("Da xuat du lieu ra access_logs.csv!")
# 6. Chay thu chuong trinh
if __name__ == "__main__":
    create_database()
    save_log("ACCESS", "SUCCESS", "Truy cap thanh cong")
    save_log("ACCESS", "FAILED", "Sai mat khau")
    save_log("DOOR", "OPEN", "Cua da mo")
    save_log("DOOR", "CLOSE", "Cua da dong")
    save_log("ALARM", "ACTIVE", "Kich hoat bao dong")
    print("\nDANH SACH NHAT KY:")
    for log in get_logs():
        print(log)
    export_csv()
