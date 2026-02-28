from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from ..models import Project
from ..logger import get_logger

logger = get_logger("Workflow")

class BaseWorkflow:
    def __init__(self, db: Session, project_id: str):
        self.db = db
        self.project_id = project_id
        self.project: Optional[Project] = db.query(Project).filter(Project.id == project_id).first()

    def log(self, message: str):
        """Logs a message to the project's ingestion_logs and backend logs."""
        logger.info(f"[{self.project_id}] {message}")
        if self.project:
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
            # Initialize if None
            if self.project.ingestion_logs is None:
                self.project.ingestion_logs = []
            
            # Append log (create new list to ensure SQLAlchemy detects change)
            self.project.ingestion_logs = self.project.ingestion_logs + [f"[{timestamp}] {message}"]
            self.db.commit()

    def update_progress(self, progress: int, status: str = None):
        """Updates the project's RAG status and progress."""
        if self.project:
            self.project.rag_progress = int(progress)
            if status:
                self.project.rag_status = status
            # Clear workflow config when completed or errored
            if status in ('ready', 'error'):
                from sqlalchemy.orm.attributes import flag_modified
                config = dict(self.project.config or {})
                config.pop('workflow', None)
                self.project.config = config
                flag_modified(self.project, "config")
            self.db.commit()

    def is_cancelled(self) -> bool:
        """Checks if the workflow was cancelled (status reset to 'ready' externally)."""
        self.db.refresh(self.project)
        return self.project.rag_status != "processing"

    def fail(self, error: Exception):
        """Logs failure and updates status."""
        self.log(f"Workflow Failed: {str(error)}")
        if self.project:
            self.project.rag_status = "error"
            from sqlalchemy.orm.attributes import flag_modified
            config = dict(self.project.config or {})
            config.pop('workflow', None)
            self.project.config = config
            flag_modified(self.project, "config")
            self.db.commit()
