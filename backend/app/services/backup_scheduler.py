import asyncio
import logging
from ..database import SessionLocal
from ..models import Project
from .settings_service import get_app_settings
from .backup_service import BackupService

logger = logging.getLogger("BackupScheduler")


async def backup_loop():
    """Background loop that auto-backs up active projects at the configured interval."""
    # Wait a bit on startup before first run
    await asyncio.sleep(30)

    while True:
        interval_minutes = 10
        try:
            db = SessionLocal()
            try:
                settings = get_app_settings(db)
                backup_dir = settings.get("backup_dir", "")
                interval_minutes = settings.get("backup_interval_minutes", 10)
                max_count = settings.get("backup_max_count", 3)
                include_files = settings.get("backup_include_files", True)

                if backup_dir:
                    projects = db.query(Project).filter(Project.archived == False).all()
                    svc = BackupService(db)
                    for p in projects:
                        try:
                            svc.save_backup_to_disk(p.id, backup_dir, max_count, include_files)
                        except Exception as e:
                            logger.error(f"Backup failed for project {p.id}: {e}")
                    if projects:
                        logger.info(f"Auto-backup complete: {len(projects)} project(s)")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Backup scheduler error: {e}")

        await asyncio.sleep(interval_minutes * 60)


def start_backup_scheduler():
    """Create the backup loop as an asyncio task. Call from FastAPI startup."""
    asyncio.ensure_future(backup_loop())
    logger.info("Backup scheduler started")
