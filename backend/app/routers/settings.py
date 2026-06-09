import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.settings_service import get_app_settings, update_app_settings
from ..core.config import settings as app_config
from ..logger import get_logger

router = APIRouter(prefix="/settings", tags=["settings"])
logger = get_logger("SettingsRouter")


@router.get("/")
def get_settings(db: Session = Depends(get_db)):
    """Return global app settings + ENV info (read-only)."""
    s = get_app_settings(db)
    return {
        "settings": s,
        "env": {
            "db_host": app_config.DB_HOST,
            "db_port": app_config.DB_PORT,
            "db_user": app_config.DB_USER,
            "db_name": app_config.DB_NAME,
            "storage_root": os.getenv("STORAGE_ROOT", "storage"),
        },
        "version": app_config.PROJECT_VERSION,
    }


@router.patch("/")
def patch_settings(updates: dict, db: Session = Depends(get_db)):
    """Update global app settings."""
    try:
        updated = update_app_settings(db, updates)
        return {"settings": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/version")
def get_version():
    return {"version": app_config.PROJECT_VERSION}


def _browse_root() -> str:
    """Confinement root for the directory picker (user's home directory)."""
    return os.path.realpath(os.path.expanduser("~"))


def _is_within_root(resolved_path: str, root: str) -> bool:
    """True if resolved_path is the root or nested under it (post-realpath)."""
    try:
        return os.path.commonpath([resolved_path, root]) == root
    except ValueError:
        # Different drives on Windows -> not comparable
        return False


@router.get("/browse-dirs")
def browse_directories(path: str = ""):
    """List subdirectories of a given path for the directory picker.

    Confined to the user's home directory to prevent enumerating arbitrary
    server paths (e.g. ?path=/etc).
    """
    root = _browse_root()

    # Default to home directory
    if not path:
        path = root

    path = os.path.expanduser(path)

    # Resolve symlinks (e.g. ~/OneDrive -> ~/Library/CloudStorage/OneDrive-...)
    path = os.path.realpath(path)

    if not _is_within_root(path, root):
        raise HTTPException(status_code=403, detail="Path outside allowed directory")

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Not a directory")

    try:
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                entries.append(name)

        # When browsing home dir, inject cloud storage folders as shortcuts
        cloud_shortcuts = []
        home = os.path.expanduser("~")
        if os.path.realpath(path) == os.path.realpath(home):
            cloud_root = os.path.join(home, "Library", "CloudStorage")
            if os.path.isdir(cloud_root):
                try:
                    for name in sorted(os.listdir(cloud_root)):
                        full = os.path.join(cloud_root, name)
                        if os.path.isdir(full) and not name.startswith("."):
                            cloud_shortcuts.append({"name": f"☁ {name}", "path": full})
                except PermissionError:
                    pass

        # Clamp parent so the UI cannot navigate above the confinement root.
        parent = os.path.dirname(os.path.abspath(path))
        if not _is_within_root(os.path.realpath(parent), root):
            parent = None

        return {
            "current": os.path.abspath(path),
            "parent": parent,
            "directories": entries,
            "cloud_shortcuts": cloud_shortcuts,
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")


@router.post("/backup/{project_id}")
async def trigger_manual_backup(project_id: str, db: Session = Depends(get_db)):
    """Trigger a manual backup for a specific project."""
    from ..services.backup_service import BackupService
    s = get_app_settings(db)
    backup_dir = s.get("backup_dir", "")
    if not backup_dir:
        raise HTTPException(status_code=400, detail="No backup directory configured")

    svc = BackupService(db)
    try:
        path = svc.save_backup_to_disk(
            project_id, backup_dir,
            max_count=s.get("backup_max_count", 3),
            include_files=s.get("backup_include_files", True),
            skip_if_unchanged=False,
        )
        return {"path": path}
    except Exception as e:
        logger.exception("manual_backup_failed", project_id=project_id)
        raise HTTPException(status_code=500, detail="Backup failed")


@router.get("/backups")
def list_backups(db: Session = Depends(get_db)):
    """List all backup files in the configured backup directory."""
    from ..services.backup_service import BackupService
    s = get_app_settings(db)
    backup_dir = s.get("backup_dir", "")
    if not backup_dir:
        return {"backups": []}

    svc = BackupService(db)
    return {"backups": svc.list_backups(backup_dir)}


@router.post("/restore")
async def restore_from_backup(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a .logion.zip backup and restore it as a new project."""
    from ..services.backup_service import BackupService
    if not file.filename.endswith(".logion.zip"):
        raise HTTPException(status_code=400, detail="File must be a .logion.zip backup")

    zip_data = await file.read()
    svc = BackupService(db)
    try:
        project = svc.restore_project_from_zip(zip_data)
        return {"project_id": project.id, "name": project.name}
    except Exception as e:
        logger.exception("restore_failed", filename=file.filename)
        raise HTTPException(status_code=500, detail="Restore failed")
