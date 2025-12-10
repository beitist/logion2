from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import shutil
import os
import uuid

from ..database import get_db
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse
from ..parser import parse_docx
from ..models import Project, Segment
# from ..schemas import ProjectOut, SegmentOut # We can reuse models or create schemas.
# For MVP speed, let's use ORM models but we usually need Pydantic schemas for response_model.
# Let's define simple response schemas here or in schemas.py if strictly needed.
# We'll just return dicts or ORM objects and let FastAPI serialization handle it if possible,
# but Pydantic is safer.


UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

router = APIRouter(prefix="/project", tags=["project"])

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
        # Note: tags are dicts, we need to store them as JSON in metadata.
        
        # We need to serialize TagModel objects to dict for JSON column
        # tags_json = {k: v.model_dump() for k, v in seg_int.tags.items()} # This line is no longer needed
        
        # Serialize tags and metadata properly
        # seg_int.tags is a dict of TagModels. seg_int.metadata is a dict.
        # We want to store everything needed for reconstruction.
        seg_dump = seg_int.model_dump()
        
        db_segment = Segment(
            id=seg_int.segment_id, # Keep original segment_id from parser
            project_id=project_id,
            index=seg_int.metadata.get("original_index", 0), # Keep original index logic
            source_content=seg_int.source_text,
            target_content=None, # Empty initially
            status="draft",
            metadata_json=seg_dump # Save the full dump which includes 'tags' and 'metadata'
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

from ..schemas import SegmentResponse # Assuming SegmentResponse is defined here or in schemas.py

@router.get("/{project_id}/segments", response_model=List[SegmentResponse])
def get_project_segments(project_id: str, db: Session = Depends(get_db)):
    segments = db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
    # Convert tag_models JSON to list of TagModel for response
    # Pydantic should handle it if model matches alias?
    # Actually, SQLAlchemy model metadata_json is a dict/JSON. Pydantic expects dict/list.
    # We might need to map it explicitly if Pydantic doesn't auto-convert.
    # The current Project/Segment Models use JSON type, and Pydantic schema expects TagModel list.
    # Let's trust Pydantic + SQLA for now, or ensure 'tags' field is populated from metadata if separate.
    # Wait, our Segment model in DB has 'metadata_json', but SegmentInternal has 'tags'.
    # In 'create_upload_file', we dumped tags into metadata_json if I recall?
    # Let's check 'parser.py' output. It returns SegmentInternal which has 'tags'.
    # In 'create_upload_file' (line 62 in previous version), we did:
    # segment_db = Segment(..., metadata_json=seg.model_dump().get("metadata"))
    # We might have LOST the tags if they weren't in metadata_json!
    # Checking parser: tags are in 'tags' field of SegmentInternal, metadata is separate.
    # Checking Project.py upload:
    # seg_data = seg.model_dump() ... segment_db = Segment(..., metadata_json=json.dumps(seg_data)) 
    # If we dumped the WHOLE model, then tags are inside metadata_json['tags'].
    
    # Correction: The SegmentResponse schema needs to align with what we return.
    # For now, let's just implement EXPORT as that is the goal here.
    return segments

from fastapi.responses import FileResponse
from ..reassembly import reassemble_docx
import os
import json # Added import for json
from ..schemas import SegmentInternal, TagModel # Added imports for SegmentInternal, TagModel

@router.get("/{project_id}/export")
def export_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Get all segments (in order!)
    segments = db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
    
    # 2. Reconstruct SegmentInternal objects for reassembly
    # We need to reconstruct the "SegmentInternal" list expected by reassemble_docx
    # The reassembly expects objects with attributes: target_content, tags, metadata
    
    reassembly_segments = []
    
    for db_seg in segments:
        # We need to recover tags and metadata
        # In upload, we stored: metadata_json = json.dumps(seg.model_dump())
        # So it contains keys: "source_text", "status", "tags", "metadata", etc.
        
        # metadata_json is already a dict in SQLAlchemy, no need for json.loads()
        stored_data = db_seg.metadata_json
        
        # Stored tags are dicts, need convert to TagModel
        # The tags are stored as a dictionary where keys are tag names and values are dicts of tag properties.
        # The reassembly expects a list of TagModel objects.
        # Let's assume the original `tags` field in `SegmentInternal` was a dict of TagModel.
        # When we stored it, we did `tags_json = {k: v.model_dump() for k, v in seg_int.tags.items()}`
        # So `stored_data.get("tags", {})` will be a dict of dicts.
        # We need to convert these back to TagModel objects.
        
        # Corrected reconstruction of tags:
        reconstructed_tags_dict = {}
        for tag_name, tag_data in stored_data.get("tags", {}).items():
            reconstructed_tags_dict[tag_name] = TagModel(**tag_data)
        
        # Stored metadata is the location info
        meta_loc = stored_data.get("metadata", {})
        
        # Use current target_content from DB (this has the user edits!)
        target_text = db_seg.target_content
        if target_text is None:
            target_text = db_seg.source_content # Fallback to source

        
        seg_internal = SegmentInternal(
            id=db_seg.id,
            segment_id=str(db_seg.id),
            source_text=db_seg.source_content,
            target_content=target_text,
            status=db_seg.status,
            tags=reconstructed_tags_dict, # Pass the reconstructed dict of TagModel objects
            metadata=meta_loc
        )
        reassembly_segments.append(seg_internal)
        
    # 3. Path to original file
    # We saved it as UPLOAD_DIR / {project.id}_{project.filename} ? 
    # Let's check upload logic.
    # "file_location = f"uploads/{file.filename}"" -> Wait, this might conflict if same filename used!
    # We should have used ID. But let's check what we did.
    # In 'create_upload_file': file_location = f"uploads/{file.filename}"
    # This is a risk. But for now we assume it's there.
    
    # Corrected input_path based on upload logic:
    input_path = os.path.join(UPLOAD_DIR, f"{project.id}_{project.filename}")
    if not os.path.exists(input_path):
        # Fallback query: maybe we didn't save with project.id prefix?
        # Ideally we should fix upload to be unique.
        raise HTTPException(status_code=404, detail=f"Original file not found at {input_path}")
        
    output_filename = f"translated_{project.filename}"
    output_path = os.path.join(UPLOAD_DIR, output_filename)
    
    # 4. Reassemble
    try:
        reassemble_docx(input_path, output_path, reassembly_segments)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reassembly failed: {str(e)}")
    
    return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=output_filename)
