import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.settings_service import get_app_settings, update_app_settings
from ..core.config import settings as app_config

router = APIRouter(prefix="/settings", tags=["settings"])


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


@router.get("/browse-dirs")
def browse_directories(path: str = ""):
    """List subdirectories of a given path for the directory picker."""
    # Default to home directory
    if not path:
        path = os.path.expanduser("~")

    path = os.path.expanduser(path)

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    try:
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                entries.append(name)
        return {
            "current": os.path.abspath(path),
            "parent": os.path.dirname(os.path.abspath(path)),
            "directories": entries,
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
        )
        return {"path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))
