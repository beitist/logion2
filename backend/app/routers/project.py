from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import shutil
import os
import uuid
import hashlib
from bs4 import BeautifulSoup
import re
from docx import Document
from datetime import datetime

from ..database import get_db, SessionLocal, engine
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse, ProjectUpdate, ProjectListResponse, ProjectFileSchema
from ..parser import parse_docx
from ..models import Project, Segment, ProjectFile, ProjectFileCategory

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

router = APIRouter(prefix="/project", tags=["project"])

@router.get("/", response_model=List[ProjectListResponse])
def get_projects(db: Session = Depends(get_db)):
    """
    Returns a list of all projects.
    """
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return projects

@router.post("/create", response_model=ProjectResponse)
async def create_project(
    name: str = Form(...),
    source_lang: str = Form("en"),
    target_lang: str = Form("de"),
    use_ai: bool = Form(False),
    source_files: List[UploadFile] = File(None),
    legal_files: List[UploadFile] = File(None),
    background_files: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Creates a new project with multiple files and settings.
    Parses the first valid source DOCX for segments.
    """
    project_id = str(uuid.uuid4())
    
    # Create Project Record
    new_project = Project(
        id=project_id,
        name=name,
        filename=source_files[0].filename if source_files else "Untitled", # Main filename
        status="processing",
        source_lang=source_lang,
        target_lang=target_lang,
        use_ai=use_ai,
        created_at=datetime.utcnow()
    )
    db.add(new_project)
    db.commit() # Commit to get ID for relationships if needed (though we set UUID manually)

    primary_source_docx = None

    # Helper to process files
    async def process_files(files, category: ProjectFileCategory):
        nonlocal primary_source_docx
        if not files: return
        
        for file in files:
            if not file.filename: continue
            
            # Create unique object name
            # Format: {project_id}/{category}/{filename}
            object_name = f"{project_id}/{category.value}/{file.filename}"
            
            # Upload to MinIO
            from ..storage import upload_file
            
            try:
                # We need to read the file to upload
                # file.file is a SpooledTemporaryFile
                # Move cursor to start just in case
                await file.seek(0)
                uploaded_obj = upload_file(file.file, object_name, content_type=file.content_type)
                
                # Create ProjectFile record (store object_name as file_path)
                db_file = ProjectFile(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    category=category.value,
                    filename=file.filename,
                    file_path=uploaded_obj
                )
                db.add(db_file)
                
                # Identify primary source for parsing
                # For parsing we might need to download it later or parse now.
                # Since 'parse_docx' expects a path, we might need to download it to a temp path.
                if category == ProjectFileCategory.source and file.filename.endswith(".docx") and not primary_source_docx:
                    primary_source_docx = object_name
                    
            except Exception as e:
                print(f"Failed to upload {file.filename}: {e}")
                # Log error but maybe continue?
                pass

    # Process all file categories
    await process_files(source_files, ProjectFileCategory.source)
    await process_files(legal_files, ProjectFileCategory.legal)
    await process_files(background_files, ProjectFileCategory.background)
    
    db.commit()

    # Parse segments if we have a source docx
    from ..storage import download_file
    
    if primary_source_docx:
        temp_parse_path = os.path.join(UPLOAD_DIR, f"temp_{project_id}.docx")
        try:
            # Download from MinIO
            download_file(primary_source_docx, temp_parse_path)
            
            segments_internal = parse_docx(temp_parse_path)
            
            for seg_int in segments_internal:
                seg_dump = seg_int.model_dump()
                db_segment = Segment(
                    id=seg_int.segment_id,
                    project_id=project_id,
                    index=seg_int.metadata.get("original_index", 0),
                    source_content=seg_int.source_text,
                    target_content=None,
                    status="draft",
                    metadata_json=seg_dump
                )
                db.add(db_segment)
            
            # Update project status or simple message?
            new_project.status = "review" # Ready for review after parsing
            db.add(new_project)
            db.commit()
            
        except Exception as e:
            db.delete(new_project)
            db.commit()
            raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
        finally:
             if os.path.exists(temp_parse_path):
                 os.remove(temp_parse_path)

    db.refresh(new_project)
    return new_project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/segments", response_model=List[SegmentResponse])
def get_project_segments(project_id: str, db: Session = Depends(get_db)):
    segments = db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
    
    response_list = []
    for s in segments:
        stored_meta = s.metadata_json or {}
        tags_data = stored_meta.get("tags")
        
        seg_dict = {
            "id": s.id,
            "index": s.index,
            "source_content": s.source_content,
            "target_content": s.target_content,
            "status": s.status,
            "project_id": s.project_id,
            "tags": tags_data
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
        
    # 3. Path to original file (Source)
    # We need to find the source file for this project
    source_file_record = db.query(ProjectFile).filter(
        ProjectFile.project_id == project_id, 
        ProjectFile.category == ProjectFileCategory.source.value
    ).first()

    if not source_file_record:
        # Fallback to old behavior for migration or errors?
        # Try to find file by hash or legacy methods if needed, but for new system:
        raise HTTPException(status_code=404, detail="Original source file not found for project")
    
    # Check if file_path looks like a MinIO object path (no leading slash, etc) or absolute path
    # New system uses object path. Old system used absolute path.
    # Simple heuristic:
    input_object_name = source_file_record.file_path
    
    # Temp input path
    temp_input_path = os.path.join(UPLOAD_DIR, f"temp_export_in_{project_id}.docx")
    
    from ..storage import download_file, upload_file
    
    try:
        download_file(input_object_name, temp_input_path)
    except Exception as e:
         # Try legacy local path check?
         if os.path.exists(input_object_name):
             # It was a local path
             shutil.copy(input_object_name, temp_input_path)
         else:
             raise HTTPException(status_code=404, detail=f"Source file download failed: {e}")

    output_filename = f"translated_{project.filename}"
    output_path = os.path.join(UPLOAD_DIR, output_filename)
    
    # 4. Reassemble
    try:
        reassemble_docx(temp_input_path, output_path, reassembly_segments)
    except Exception as e:
        import traceback
        with open("export_error.log", "w") as f:
            f.write(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Reassembly failed: {str(e)}")
    finally:
        # Cleanup input temp
        if os.path.exists(temp_input_path):
            os.remove(temp_input_path)
    
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
