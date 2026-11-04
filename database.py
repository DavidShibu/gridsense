import sqlite3
import time

DB_PATH = "gridsense.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                charger_id TEXT NOT NULL,
                power_kw REAL NOT NULL,
                soc REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)


def save_telemetry(data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO telemetry
            (timestamp, charger_id, power_kw, soc, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.get("timestamp", time.time()),
                data["charger_id"],
                data["power_kw"],
                data["soc"],
                data["status"],
            ),
        )


def get_recent_telemetry(limit=20):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT timestamp, charger_id, power_kw, soc, status
            FROM telemetry
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"SQLite database initialized: {DB_PATH}")
