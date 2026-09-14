# This is your first monitoring component.

from prometheus_client import Counter


DEVICE_MESSAGES_TOTAL = Counter(
    "device_messages_total",
    "Total number of messages received from devices"
)


CLOUD_FORWARD_FAILURES_TOTAL = Counter(
    "cloud_forward_failures_total",
    "Total number of failed attempts to forward data to cloud"
)