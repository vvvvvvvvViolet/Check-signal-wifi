from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway data directory before anything imports config.
_TMP = tempfile.mkdtemp(prefix="csw-test-")
os.environ.setdefault("CSW_DATA_DIR", _TMP)
os.environ.setdefault("CSW_EXPORT_DIR", str(Path(_TMP) / "exports"))
os.environ.setdefault("CSW_DATABASE_URL", f"sqlite:///{Path(_TMP) / 'test.db'}")
os.environ.setdefault("CSW_WIFI_BACKEND", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from backend.app.config import AppSettings  # noqa: E402
from backend.app.db import init_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the tables once.

    The app does this in its lifespan, but tests that talk to the database
    directly never start the app.
    """
    init_db()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings()
