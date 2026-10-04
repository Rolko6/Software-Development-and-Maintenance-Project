from prometheus_client import Counter


SECURE_DATA_RECEIVED_TOTAL = Counter(
    "secure_data_received_total",
    "Total number of successfully decrypted /data/secure requests"
)


SECURE_DATA_REJECTED_TOTAL = Counter(
    "secure_data_rejected_total",
    "Total number of rejected /data/secure requests",
    ["reason"]
)


LEGACY_DATA_RECEIVED_TOTAL = Counter(
    "legacy_data_received_total",
    "Total number of requests received on the legacy unencrypted /data endpoint"
)
