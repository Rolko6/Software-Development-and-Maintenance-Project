import os


LEGACY_INGESTION_ENV = "CLOUD_ALLOW_LEGACY_INGESTION"


def load_allow_legacy_ingestion() -> bool:
    """Return the explicitly configured legacy-ingestion compatibility policy."""
    raw_value = os.getenv(LEGACY_INGESTION_ENV, "false")
    normalized_value = raw_value.strip().lower()

    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False

    raise RuntimeError(
        f"{LEGACY_INGESTION_ENV} must be exactly 'true' or 'false' "
        "(ignoring case and surrounding whitespace)"
    )


ALLOW_LEGACY_INGESTION = load_allow_legacy_ingestion()
