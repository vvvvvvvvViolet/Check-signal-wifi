"""Load/save :class:`AppSettings` through the single-row settings table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_SETTINGS, AppSettings
from ..models import SettingRecord

_KEY = "app"


def load_settings(session: Session) -> AppSettings:
    """Return stored settings, falling back to defaults per-field.

    Validating rather than trusting the blob matters: a settings file written by
    an older version is missing keys, and a half-configured app is worse than a
    defaulted one.
    """
    record = session.get(SettingRecord, _KEY)
    if record is None:
        return DEFAULT_SETTINGS.model_copy(deep=True)
    try:
        return AppSettings.model_validate(record.value)
    except Exception:
        return DEFAULT_SETTINGS.model_copy(deep=True)


def save_settings(session: Session, settings: AppSettings) -> AppSettings:
    record = session.get(SettingRecord, _KEY)
    payload = settings.model_dump(mode="json")
    if record is None:
        session.add(SettingRecord(key=_KEY, value=payload))
    else:
        record.value = payload
    session.commit()
    return settings


def reset_settings(session: Session) -> AppSettings:
    defaults = DEFAULT_SETTINGS.model_copy(deep=True)
    return save_settings(session, defaults)


def has_stored_settings(session: Session) -> bool:
    return session.scalar(select(SettingRecord.key).where(SettingRecord.key == _KEY)) is not None
