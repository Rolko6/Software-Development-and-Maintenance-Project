from prometheus_client import Counter


SECURE_DATA_RECEIVED_TOTAL = Counter(
    "secure_data_received_total",
    "Total number of securely received readings committed to storage"
)


SECURE_DATA_REJECTED_TOTAL = Counter(
    "secure_data_rejected_total",
    "Total number of secure requests rejected during application processing",
    ["reason"]
)


LEGACY_DATA_RECEIVED_TOTAL = Counter(
    "legacy_data_received_total",
    "Total number of readings stored through the legacy unencrypted /data endpoint"
)


LEGACY_DATA_REJECTED_TOTAL = Counter(
    "legacy_data_rejected_total",
    "Total number of requests rejected on the legacy unencrypted /data endpoint"
)


SECURE_DATA_REJECTION_REASONS = (
    "decryption_failed",
    "malformed_payload",
    "stale_timestamp",
    "validation_failed",
    "storage_failed",
)

# Pre-create every supported label so a fresh /metrics response exposes zeros
# instead of omitting time series that have not been observed yet.
for rejection_reason in SECURE_DATA_REJECTION_REASONS:
    SECURE_DATA_REJECTED_TOTAL.labels(reason=rejection_reason)
