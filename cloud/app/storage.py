# Later, you could replace this with SQLite or PostgreSQL.
# But I recommend not doing that immediately.

import os
from collections import deque

from .metrics import (
    CLOUD_READINGS_STORED_TOTAL,
    CLOUD_STORAGE_EVICTIONS_TOTAL,
    CLOUD_STORED_READINGS
)


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
    # deque(maxlen=...) drops the oldest item silently once full, so the
    # eviction has to be detected here: if we are already at capacity, this
    # append will evict exactly one reading.
    if len(stored_data) == stored_data.maxlen:
        CLOUD_STORAGE_EVICTIONS_TOTAL.inc()

    stored_data.append(data)

    CLOUD_READINGS_STORED_TOTAL.inc()
    CLOUD_STORED_READINGS.set(len(stored_data))


def get_all_data():
    return list(stored_data)


def clear_data():
    """Remove all stored readings.

    Used by the test suite for isolation between tests; also a reasonable
    operational reset hook.
    """
    stored_data.clear()
    CLOUD_STORED_READINGS.set(0)