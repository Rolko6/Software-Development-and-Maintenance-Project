# Later, you could replace this with SQLite or PostgreSQL.
# But I recommend not doing that immediately.

stored_data = []


def save_sensor_data(data: dict):
    stored_data.append(data)


def get_all_data():
    return stored_data