# This is your first monitoring component.

from prometheus_client import Counter, Gauge

from app.sensor_state import SENSOR_STATE


DEVICE_MESSAGES_TOTAL = Counter(
    "device_messages_total",
    "Total number of messages received from devices"
)


CLOUD_FORWARD_FAILURES_TOTAL = Counter(
    "cloud_forward_failures_total",
    "Total number of failed attempts to forward data to cloud"
)


CLOUD_FORWARD_ATTEMPTS_TOTAL = Counter(
    "cloud_forward_attempts_total",
    "Total number of admitted attempts to forward sensor data to cloud",
)


SENSOR_FAULT_READINGS_TOTAL = Counter(
    "sensor_fault_readings_total",
    "Total number of DS18B20 error-sentinel readings received from a device",
    ["type"]
)


SENSOR_READ_FAILURES_TOTAL = Counter(
    "sensor_read_failures_total",
    "Total number of explicit failed sensor-read reports received from devices",
)


SENSOR_STUCK_EPISODES_TOTAL = Counter(
    "sensor_stuck_episodes_total",
    "Total number of suspected stuck-sensor episodes detected",
)


SENSOR_DISCONNECTED_DEVICES = Gauge(
    "sensor_disconnected_devices",
    "Current number of devices whose latest report was a disconnected sensor",
)


SENSOR_SUSPECTED_STUCK_DEVICES = Gauge(
    "sensor_suspected_stuck_devices",
    "Current number of devices at the configured identical-reading threshold",
)


SENSOR_SILENT_DEVICES = Gauge(
    "sensor_silent_devices",
    "Current number of devices beyond the configured no-contact timeout",
)


# Create every bounded sentinel label series even before the first event.
for _fault_type in ("power_on_reset", "crc_failure"):
    SENSOR_FAULT_READINGS_TOTAL.labels(type=_fault_type)


# set_function evaluates current state for every scrape, so silence continues to
# change even when the gateway receives no requests.
SENSOR_DISCONNECTED_DEVICES.set_function(SENSOR_STATE.disconnected_count)
SENSOR_SUSPECTED_STUCK_DEVICES.set_function(SENSOR_STATE.suspected_stuck_count)
SENSOR_SILENT_DEVICES.set_function(SENSOR_STATE.silent_count)
