from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import shutil
import os
import uuid

from ..database import get_db
from ..models import Project, Segment
from ..parser import parse_docx
# from ..schemas import ProjectOut, SegmentOut # We can reuse models or create schemas. 
# For MVP speed, let's use ORM models but we usually need Pydantic schemas for response_model.
# Let's define simple response schemas here or in schemas.py if strictly needed.
# We'll just return dicts or ORM objects and let FastAPI serialization handle it if possible, 
# but Pydantic is safer.

router = APIRouter(prefix="/project", tags=["project"])

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

@router.post("/upload")
def upload_project(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Uploads a DOCX, parses it, and creates a Project with Segments.
    """
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Only DOCX files allowed")

    # 1. Save File
    project_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{project_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Parse File
    try:
        segments_internal = parse_docx(file_path)
    except Exception as e:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
        
    # 3. Create Project Record
    new_project = Project(
        id=project_id,
        filename=file.filename,
        status="processing" # or review immediately?
    )
    db.add(new_project)
    
    # 4. Create Segment Records
    for seg_int in segments_internal:
        # segment_id from parser might be random, but we can reuse it.
        # Note: tags are dicts, we need to store them as JSON in metadata.
        
        # We need to serialize TagModel objects to dict for JSON column
        tags_json = {k: v.model_dump() for k, v in seg_int.tags.items()}
        
        db_segment = Segment(
            id=seg_int.segment_id,
            project_id=project_id,
            index=seg_int.metadata.get("original_index", 0),
            source_content=seg_int.source_text,
            target_content=None, # Empty initially
            status="draft",
            metadata_json=tags_json # Storing map directly in metadata_json column
        )
        db.add(db_segment)
        
    db.commit()
    
    return {"id": project_id, "filename": file.filename, "segments_count": len(segments_internal)}

@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.get("/{project_id}/segments")
def get_segments(project_id: str, db: Session = Depends(get_db)):
    segments = db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
    if not segments:
         # Could be empty project, but let's return empty list
         return []
    return segments
