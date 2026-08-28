"""The continuous-monitoring engine.

One asyncio task samples the link on an interval, writes it to the database,
detects roams and fans the result out to every connected WebSocket. It is a
singleton because there is exactly one radio to read - two loops would halve
the effective interval and interleave confusing readings.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import UTC, datetime

from ..db import SessionLocal
from ..models import MonitorSession, RoamEvent, Sample
from . import retention
from .probe import snapshot_to_sample_kwargs, take_snapshot
from .roaming import RoamDetector
from .settings_store import load_settings

log = logging.getLogger(__name__)

# What the UI backfills a freshly-opened chart with.
LIVE_BUFFER_SIZE = 600


class MonitorEngine:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._buffer: deque[dict] = deque(maxlen=LIVE_BUFFER_SIZE)
        self._roam_buffer: deque[dict] = deque(maxlen=200)
        self._detector = RoamDetector()
        self._session_id: int | None = None
        self._lock = asyncio.Lock()
        self._last_snapshot: dict | None = None
        self._error: str | None = None

    # ------------------------------------------------------------- state
    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "session_id": self._session_id,
            "buffered_samples": len(self._buffer),
            "subscribers": len(self._subscribers),
            "last_error": self._error,
            "last_sample_at": self._last_snapshot["ts"] if self._last_snapshot else None,
        }

    def recent(self, limit: int = LIVE_BUFFER_SIZE) -> list[dict]:
        return list(self._buffer)[-limit:]

    def recent_roams(self, limit: int = 50) -> list[dict]:
        return list(self._roam_buffer)[-limit:]

    # ----------------------------------------------------------- control
    async def start(
        self,
        *,
        name: str = "Monitor session",
        area: str | None = None,
        device: str | None = None,
        note: str | None = None,
        interval_sec: float | None = None,
    ) -> dict:
        async with self._lock:
            if self.is_running:
                return self.status()

            with SessionLocal() as db:
                settings = load_settings(db)
                interval = interval_sec or settings.monitor.interval_sec

                # Prune here rather than on a timer: it is the one moment we know
                # the database is about to grow, and it costs one query against
                # an indexed column.
                try:
                    retention.prune(db, settings.monitor.retention_days)
                except Exception:  # housekeeping must never block a survey
                    log.exception("Retention prune failed; starting the session anyway")

                session = MonitorSession(
                    name=name,
                    area=area,
                    device=device,
                    note=note,
                    interval_sec=interval,
                    started_at=datetime.now(UTC),
                )
                db.add(session)
                db.commit()
                self._session_id = session.id

            self._detector.reset()
            self._buffer.clear()
            self._roam_buffer.clear()
            self._error = None
            self._task = asyncio.create_task(self._run(interval), name="csw-monitor")
            log.info("Monitor session %s started at %.1fs interval", self._session_id, interval)
            return self.status()

    async def stop(self) -> dict:
        async with self._lock:
            task, self._task = self._task, None
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            if self._session_id is not None:
                with SessionLocal() as db:
                    session = db.get(MonitorSession, self._session_id)
                    if session is not None and session.ended_at is None:
                        session.ended_at = datetime.now(UTC)
                        db.commit()
            status = self.status()
            status["running"] = False
            self._session_id = None
            return status

    # -------------------------------------------------------------- loop
    async def _run(self, interval: float) -> None:
        try:
            while True:
                started = asyncio.get_running_loop().time()
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._error = str(exc)
                    log.exception("Monitor tick failed")
                    await self._publish({"type": "error", "message": str(exc)})
                # Subtract the work we just did so the cadence stays honest.
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(0.1, interval - elapsed))
        except asyncio.CancelledError:
            log.info("Monitor loop cancelled")
            raise

    async def _tick(self) -> None:
        with SessionLocal() as db:
            settings = load_settings(db)

        snapshot = await take_snapshot(settings)
        self._last_snapshot = snapshot
        self._error = None

        roam = self._detector.observe(snapshot["link"])

        with SessionLocal() as db:
            sample = Sample(session_id=self._session_id, **snapshot_to_sample_kwargs(snapshot))
            db.add(sample)
            if roam is not None:
                data = roam.as_dict()
                db.add(
                    RoamEvent(
                        session_id=self._session_id,
                        ssid=data["ssid"],
                        from_bssid=data["from_bssid"],
                        to_bssid=data["to_bssid"],
                        from_rssi=data["from_rssi"],
                        to_rssi=data["to_rssi"],
                        from_channel=data["from_channel"],
                        to_channel=data["to_channel"],
                        gap_ms=data["gap_ms"],
                    )
                )
            db.commit()
            sample_id = sample.id

        payload = {"type": "sample", "id": sample_id, "session_id": self._session_id, **snapshot}
        self._buffer.append(payload)
        await self._publish(payload)

        if roam is not None:
            event = {"type": "roam", "ts": snapshot["ts"], **roam.as_dict()}
            self._roam_buffer.append(event)
            await self._publish(event)

    # --------------------------------------------------------- pub / sub
    def subscribe(self) -> asyncio.Queue:
        # Bounded: a stalled browser tab must not grow the queue without limit.
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def _publish(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop the oldest rather than the newest: live data beats history.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(message)


engine = MonitorEngine()
