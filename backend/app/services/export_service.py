
import os
import re
import shutil
from typing import List
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..models import Project, Segment, ProjectFile, ProjectFileCategory
from ..schemas import SegmentInternal, TagModel
from ..storage import download_file
from ..reassembly import reassemble_docx
from ..logger import get_logger

logger = get_logger("ExportService")
UPLOAD_DIR = "uploads"

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..logger import get_logger

logger = get_logger("ExportService")

class ExportService:
    def __init__(self, db: Session):
        self.db = db

    def export_project(self, project_id: str) -> FileResponse:
        from ..workflows.export import ExportWorkflow
        wf = ExportWorkflow(self.db, project_id)
        
        output_path = wf.run(format="docx")
        filename = os.path.basename(output_path)
        
        return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=filename)

    def export_project_tmx(self, project_id: str) -> FileResponse:
        from ..workflows.export import ExportWorkflow
        wf = ExportWorkflow(self.db, project_id)
        
        output_path = wf.run(format="tmx")
        filename = os.path.basename(output_path)
        
        return FileResponse(output_path, media_type="application/xml", filename=filename)
