import pytest
from fastapi.testclient import TestClient

import app.storage
from app.main import app as fastapi_app


@pytest.fixture(scope="session")
def client():
    """A TestClient shared by all cloud tests; the app has no startup state to reset."""
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def clear_stored_data():
    """Clear the module-level stored_data list before and after every test.

    stored_data lives for the whole process (see app/storage.py), so without
    this, readings saved by one test would leak into the next. We clear the
    list in place (stored_data.clear()) rather than rebinding the name,
    because get_all_data() returns the same list object it was given at
    import time -- reassigning app.storage.stored_data = [] here would leave
    that returned reference pointing at the old, now-orphaned list.
    """
    app.storage.stored_data.clear()
    yield
    app.storage.stored_data.clear()
