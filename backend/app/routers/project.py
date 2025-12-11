from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import shutil
import os
import uuid
import hashlib
from bs4 import BeautifulSoup
import re
from docx import Document

from ..database import get_db, SessionLocal, engine
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse, ProjectUpdate
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
async def upload_project(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Uploads a DOCX, parses it, and creates a Project with Segments.
    """
    if not file.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="Only DOCX files allowed")

    # Read file content for hashing and saving
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # 1. Check for existing project based on file hash
    existing_project = db.query(Project).filter(Project.file_hash == file_hash).first()
    if existing_project:
        # If a project with this hash already exists, return it
        return {"id": existing_project.id, "filename": existing_project.filename, "message": "Project already exists (based on file hash)."}

    # If not existing, proceed with new project creation
    project_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{project_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        buffer.write(content) # Write the content read earlier
        
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
        status="processing", # or review immediately?
        file_hash=file_hash # Store the hash
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
    
    # Manual mapping to Pydantic schema to ensure 'tags' are extracted from metadata_json
    response_list = []
    for s in segments:
        # metadata_json is a dict
        stored_meta = s.metadata_json or {}
        
        # Extract tags dict
        # The parser stores tags as a dict inside the model dump.
        # Check if 'tags' is a key in stored_meta
        tags_data = stored_meta.get("tags")
        
        # Ensure we return valid TagModel objects if needed, o dicts? 
        # Schema says: tags: Optional[Dict[str, TagModel]]
        # Pydantic is smart enough to convert Dict[str, dict] to Dict[str, TagModel]
        
        # Construct response object
        # We can use SegmentResponse.model_validate but we need to feed it the right dict
        seg_dict = {
            "id": s.id,
            "index": s.index,
            "source_content": s.source_content,
            "target_content": s.target_content,
            "status": s.status,
            "project_id": s.project_id,
            "tags": tags_data # Inject extracted tags here
        }
        response_list.append(seg_dict)
        
    return response_list

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
        stored_data = db_seg.metadata_json or {}
        
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
        else:
            # Cleanup Tiptap HTML
            # Tiptap usually wraps in <p>...</p>. We are injecting into an existing w:p.
            # We want to remove the outer <p> tags.
            # Simple check for now.
            # Cleanup Tiptap HTML using BeautifulSoup to handle Spans and Nesting
            # Cleanup Tiptap HTML using BeautifulSoup to handle Spans and Nesting
            if target_text:
                # 0. PRE-PROCESS: Protect existing <1> tags from BS4 escaping
                # BS4/html.parser might treat <1> as invalid and escape it to &lt;1&gt;
                # We convert them to placeholders first.
                target_text = re.sub(r'<(\d+)>', r'__TAG_START_\1__', target_text)
                target_text = re.sub(r'</(\d+)>', r'__TAG_END_\1__', target_text)

                soup = BeautifulSoup(target_text, "html.parser")
                
                # 1. Convert Tiptap Spans to Custom Tags <ID>...</ID>
                for span in soup.find_all("span", attrs={"data-type": "tag-node"}):
                    tid = span.get("data-id")
                    if tid:
                        # CASE: Generic TAB
                        if tid == 'TAB':
                            span.replace_with("[TAB]") 
                        
                        else:
                            # Detect if it is a Start or End tag based on content
                            # Frontend renders Start as "1" and End as "/1"
                            text_content = span.get_text().strip()
                            is_end_tag = text_content.startswith("/")
                            
                            # We replace the ENTIRE span (including visual label "1") with a placeholder.
                            # We use safe placeholders preventing HTML escaping issues.
                            if is_end_tag:
                                placeholder = f"__TAG_END_{tid}__"
                            else:
                                placeholder = f"__TAG_START_{tid}__"
                            
                            span.replace_with(placeholder)

                # 2. Handle Paragraphs
                # Tiptap sends <p>A</p><p>B</p>.
                # We want A<br/>B.
                ps = soup.find_all("p")
                if len(ps) > 0:
                     cleaned_html = ""
                     for i, p in enumerate(ps):
                         if i > 0: cleaned_html += "<br/>"
                         cleaned_html += p.decode_contents()
                else:
                    cleaned_html = soup.decode_contents()

                # 3. Post-Process
                # Replace placeholders with real XML-like tags <1> and </1>
                # Since we are operating on the decoded string, we insert literal < and >.
                cleaned_html = re.sub(r'__TAG_START_(\d+)__', r'<\1>', cleaned_html)
                cleaned_html = re.sub(r'__TAG_END_(\d+)__', r'</\1>', cleaned_html)
                 
                target_text = cleaned_html

        
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
        import traceback
        with open("export_error.log", "w") as f:
            f.write(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Reassembly failed: {str(e)}")
    
    return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=output_filename)

@router.delete("/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    """
    Deletes a project and all associated segments.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete segments manually to ensure cleanup
    db.query(Segment).filter(Segment.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}

@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    """
    Update project metadata (e.g. config/instructions).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)
    
    db.commit()
    db.refresh(project)
    return project
