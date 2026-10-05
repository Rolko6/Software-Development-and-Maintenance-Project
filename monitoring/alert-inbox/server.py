"""Local Alertmanager webhook inbox; notifications persist across recreation."""
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = Path(os.getenv("ALERT_INBOX_DB_PATH", "/data/alerts.sqlite3"))
MAX_BODY_BYTES = 1024 * 1024


def store_notification(payload):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH, timeout=5)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notifications "
            "(id INTEGER PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO notifications(payload) VALUES (?)", (json.dumps(payload),))
        connection.commit()


def get_notifications():
    if not DB_PATH.exists():
        return []
    with closing(sqlite3.connect(DB_PATH, timeout=5)) as connection:
        rows = connection.execute(
            "SELECT id, received_at, payload FROM notifications ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return [{"id": row[0], "received_at": row[1], "notification": json.loads(row[2])} for row in rows]


def check_storage():
    """Commit a separate readiness marker without creating a notification."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH, timeout=5)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notifications "
            "(id INTEGER PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL)"
        )
        connection.execute("CREATE TABLE IF NOT EXISTS readiness (id INTEGER PRIMARY KEY, checked_at TEXT)")
        connection.execute("INSERT OR REPLACE INTO readiness VALUES (1, CURRENT_TIMESTAMP)")
        connection.commit()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            try:
                check_storage()
                self.respond(200, {"status": "healthy"})
            except (sqlite3.Error, OSError):
                self.respond(503, {"error": "Notification storage unavailable"})
        elif self.path == "/alerts":
            try:
                self.respond(200, get_notifications())
            except sqlite3.Error:
                self.respond(503, {"error": "Notification storage unavailable"})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        self.connection.settimeout(10)
        if self.path != "/alerts":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                self.respond(413, {"error": "Invalid notification size"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or payload.get("status") not in ("firing", "resolved"):
                raise ValueError("Invalid notification status")
            store_notification(payload)
        except (ValueError, UnicodeError):
            self.respond(400, {"error": "Invalid notification"})
            return
        except (sqlite3.Error, OSError):
            self.respond(503, {"error": "Notification storage unavailable"})
            return
        logging.info("Received %s notification", payload["status"])
        self.respond(200, {"status": "stored"})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
