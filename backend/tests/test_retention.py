"""Retention must delete telemetry and must not delete anyone's saved work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from backend.app.db import SessionLocal
from backend.app.models import MonitorSession, RoamEvent, Sample, TestRecord
from backend.app.services import retention
from sqlalchemy import func, select


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _at(days_ago: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days_ago)


def test_prunes_old_samples_and_keeps_recent_ones(db):
    session = MonitorSession(name="old run", started_at=_at(120), ended_at=_at(119))
    db.add(session)
    db.commit()

    db.add_all(
        [
            Sample(session_id=session.id, ts=_at(120), rssi=-60),
            Sample(session_id=session.id, ts=_at(100), rssi=-61),
            Sample(session_id=session.id, ts=_at(5), rssi=-62),
        ]
    )
    db.commit()

    removed = retention.prune(db, retention_days=90)
    assert removed["samples"] == 2

    remaining = db.scalars(select(Sample).where(Sample.session_id == session.id)).all()
    assert [s.rssi for s in remaining] == [-62]


def test_prunes_by_row_age_not_session_age(db):
    """A long-running session must keep the samples it took this morning."""
    session = MonitorSession(name="long run", started_at=_at(200), ended_at=None)
    db.add(session)
    db.commit()
    db.add_all(
        [
            Sample(session_id=session.id, ts=_at(200), rssi=-50),
            Sample(session_id=session.id, ts=_at(0.01), rssi=-51),
        ]
    )
    db.commit()

    retention.prune(db, retention_days=90)

    remaining = db.scalars(select(Sample).where(Sample.session_id == session.id)).all()
    assert [s.rssi for s in remaining] == [-51]
    # The session itself is still running, so it survives however old it is.
    assert db.get(MonitorSession, session.id) is not None


def test_never_deletes_saved_spot_checks(db):
    """test_records are a person's deliberate work, not telemetry."""
    record = TestRecord(ts=_at(500), area="Line-A", rssi=-60, result="PASS")
    db.add(record)
    db.commit()

    retention.prune(db, retention_days=1)

    assert db.get(TestRecord, record.id) is not None


def test_prunes_roam_events(db):
    session = MonitorSession(name="roam run", started_at=_at(100), ended_at=_at(99))
    db.add(session)
    db.commit()
    db.add_all(
        [
            RoamEvent(session_id=session.id, ts=_at(100), to_bssid="AA:BB:CC:00:00:01"),
            RoamEvent(session_id=session.id, ts=_at(1), to_bssid="AA:BB:CC:00:00:02"),
        ]
    )
    db.commit()

    removed = retention.prune(db, retention_days=90)
    assert removed["roam_events"] == 1


def test_removes_finished_sessions_left_with_no_data(db):
    stale = MonitorSession(name="emptied", started_at=_at(150), ended_at=_at(149))
    db.add(stale)
    db.commit()
    db.add(Sample(session_id=stale.id, ts=_at(150), rssi=-70))
    db.commit()

    removed = retention.prune(db, retention_days=90)

    assert removed["sessions"] >= 1
    assert db.get(MonitorSession, stale.id) is None


def test_keeps_a_finished_session_that_still_has_data(db):
    session = MonitorSession(name="still useful", started_at=_at(150), ended_at=_at(149))
    db.add(session)
    db.commit()
    db.add(Sample(session_id=session.id, ts=_at(1), rssi=-55))
    db.commit()

    retention.prune(db, retention_days=90)

    assert db.get(MonitorSession, session.id) is not None


def test_rejects_a_nonsense_retention_period(db):
    with pytest.raises(ValueError, match="at least 1"):
        retention.prune(db, retention_days=0)


def test_purge_endpoint_defaults_to_the_configured_period(client):
    with SessionLocal() as db:
        db.add(Sample(ts=_at(400), rssi=-60))
        db.commit()
        before = db.scalar(select(func.count(Sample.id)).where(Sample.ts < _at(365)))
    assert before >= 1

    body = client.request("DELETE", "/api/monitor/samples").json()
    assert body["older_than_days"] == 90
    assert body["removed"]["samples"] >= 1

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Sample.id)).where(Sample.ts < _at(365))) == 0


def test_migration_adds_a_missing_column_to_an_existing_database(tmp_path):
    """A database written before `neighbors` existed must keep working.

    `create_all` creates missing tables but never alters an existing one, so
    without this the first query touching the new column would fail on anyone's
    existing install.
    """
    import sqlite3

    import backend.app.db as db_module
    from sqlalchemy import create_engine

    path = tmp_path / "legacy.db"
    legacy = create_engine(f"sqlite:///{path}")

    # Build the table as an older version would have: no `neighbors`.
    with legacy.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE survey_points ("
            "id INTEGER PRIMARY KEY, floor_plan_id INTEGER NOT NULL, "
            "ts DATETIME NOT NULL, x FLOAT NOT NULL, y FLOAT NOT NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO survey_points (floor_plan_id, ts, x, y) "
            "VALUES (1, '2026-01-01 00:00:00', 10, 20)"
        )

    original = db_module.engine
    db_module.engine = legacy
    try:
        db_module._apply_column_additions()
        db_module._apply_column_additions()  # must be safe to repeat
    finally:
        db_module.engine = original
        legacy.dispose()

    con = sqlite3.connect(path)
    try:
        columns = [row[1] for row in con.execute("PRAGMA table_info(survey_points)")]
        assert "neighbors" in columns
        # The existing row survives, with the new column empty.
        assert con.execute("SELECT neighbors FROM survey_points").fetchone()[0] is None
    finally:
        con.close()
