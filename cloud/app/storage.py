import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator


DEFAULT_DATABASE_PATH = "/data/readings.sqlite3"
SQLITE_TIMEOUT_SECONDS = 5.0

_CREATE_READINGS_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
)
"""


def validate_database_path() -> str:
    """Return the configured durable path or reject transient SQLite storage."""
    database_path = os.environ.get("CLOUD_DB_PATH", DEFAULT_DATABASE_PATH)
    normalized_path = database_path.strip()

    if normalized_path in ("", ":memory:"):
        raise RuntimeError(
            "CLOUD_DB_PATH must name a durable database file; "
            "empty and ':memory:' paths are not allowed"
        )

    return database_path


def _database_path() -> str:
    return validate_database_path()


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Open one SQLite connection for one storage operation."""
    connection = sqlite3.connect(
        _database_path(),
        timeout=SQLITE_TIMEOUT_SECONDS,
    )
    try:
        connection.execute(_CREATE_READINGS_TABLE)
        yield connection
    finally:
        connection.close()


def save_sensor_data(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    with _connection() as connection:
        # The connection context commits before this function returns and rolls
        # back if the insert or commit fails. Retention is deliberately
        # unlimited, matching the v3 in-memory storage contract.
        with connection:
            connection.execute(
                "INSERT INTO readings (payload) VALUES (?)",
                (payload,),
            )


def get_all_data() -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            "SELECT payload FROM readings ORDER BY id ASC"
        ).fetchall()

    return [json.loads(payload) for (payload,) in rows]
