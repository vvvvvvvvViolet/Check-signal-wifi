"""Automatic pruning of high-volume sampling data.

Monitoring at a one-second interval writes roughly 86,000 rows a day, so
``retention_days`` has to actually delete something or the setting is a lie and
the database grows without bound.

What is pruned and what is not is a deliberate distinction:

* ``samples`` and ``roam_events`` are machine-generated telemetry. They exist to
  draw a chart during and shortly after a survey, and are pruned by row age.
* ``test_records`` and ``survey_points`` are things a person chose to record.
  They are never pruned - deleting somebody's saved spot-check because it turned
  90 days old would be destroying their work, not housekeeping.

Pruning by *row* age rather than session age matters: a session started 100 days
ago and still running must keep the samples it took this morning.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import MonitorSession, RoamEvent, Sample

log = logging.getLogger(__name__)


def prune(db: Session, retention_days: int) -> dict[str, int]:
    """Delete telemetry older than ``retention_days``. Returns what was removed."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    samples = db.execute(delete(Sample).where(Sample.ts < cutoff)).rowcount or 0
    roams = db.execute(delete(RoamEvent).where(RoamEvent.ts < cutoff)).rowcount or 0

    # A finished session whose samples have all aged out is an empty row in the
    # session list with nothing behind it. Sessions still running are left alone
    # however old they are, and so is any session that still has data.
    empty_sessions = db.scalars(
        select(MonitorSession.id)
        .outerjoin(Sample, Sample.session_id == MonitorSession.id)
        .where(MonitorSession.ended_at.is_not(None), MonitorSession.ended_at < cutoff)
        .group_by(MonitorSession.id)
        .having(func.count(Sample.id) == 0)
    ).all()

    sessions = 0
    if empty_sessions:
        sessions = (
            db.execute(
                delete(MonitorSession).where(MonitorSession.id.in_(empty_sessions))
            ).rowcount
            or 0
        )

    db.commit()

    removed = {"samples": samples, "roam_events": roams, "sessions": sessions}
    if any(removed.values()):
        log.info(
            "Retention: pruned %d samples, %d roam events, %d empty sessions older than %d days",
            samples,
            roams,
            sessions,
            retention_days,
        )
    return removed
