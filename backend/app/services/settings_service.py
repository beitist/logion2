import os
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from ..models import AppSettings

DEFAULT_SETTINGS = {
    "backup_dir": "",
    "backup_max_count": 3,
    "backup_interval_minutes": 10,
    "backup_include_files": True,
}


def get_app_settings(db: Session) -> dict:
    """Return the singleton app settings row, creating it with defaults if missing."""
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not row:
        row = AppSettings(id=1, settings=dict(DEFAULT_SETTINGS))
        db.add(row)
        db.commit()
        db.refresh(row)
    # Merge defaults for any missing keys
    merged = {**DEFAULT_SETTINGS, **(row.settings or {})}
    return merged


def update_app_settings(db: Session, updates: dict) -> dict:
    """Merge updates into the singleton settings row. Returns updated settings."""
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not row:
        row = AppSettings(id=1, settings=dict(DEFAULT_SETTINGS))
        db.add(row)
        db.flush()

    current = {**DEFAULT_SETTINGS, **(row.settings or {})}
    current.update(updates)

    # Validate backup_dir if provided
    backup_dir = current.get("backup_dir", "")
    if backup_dir:
        try:
            os.makedirs(backup_dir, exist_ok=True)
            # Test write access
            test_file = os.path.join(backup_dir, ".logion_write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except OSError as e:
            raise ValueError(f"Backup directory not writable: {e}")

    row.settings = current
    flag_modified(row, "settings")
    db.commit()
    db.refresh(row)
    return current
