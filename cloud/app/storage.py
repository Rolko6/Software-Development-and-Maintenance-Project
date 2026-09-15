# Later, you could replace this with SQLite or PostgreSQL.
# But I recommend not doing that immediately.

import os
from collections import deque


# Bounded in-memory retention: once the limit is reached, the oldest reading
# is dropped for each new one stored, instead of growing forever. Default
# keeps the most recent 1000 readings. Readings are still lost on process
# restart; this only bounds memory growth while the process is running.
MAX_STORED_READINGS = int(os.getenv(
    "CLOUD_MAX_STORED_READINGS",
    "1000"
))

stored_data = deque(maxlen=MAX_STORED_READINGS)


def save_sensor_data(data: dict):
    stored_data.append(data)


def get_all_data():
    return list(stored_data)


def clear_data():
    """Remove all stored readings.

    Used by the test suite for isolation between tests; also a reasonable
    operational reset hook.
    """
    stored_data.clear()