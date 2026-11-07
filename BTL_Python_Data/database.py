import sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd

DB_NAME = Path(__file__).with_name("access_control.db")

def create_database():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT)""")

def save_log(event_type, status, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO access_logs(timestamp,event_type,status,detail) VALUES(?,?,?,?)",
                     (timestamp, event_type, status, detail))

def get_logs(limit=None):
    query = "SELECT * FROM access_logs ORDER BY id DESC"
    params = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql_query(query, conn, params=params)

def export_csv():
    output = Path(__file__).with_name("access_logs.csv")
    get_logs().to_csv(output, index=False, encoding="utf-8-sig")
    return output
