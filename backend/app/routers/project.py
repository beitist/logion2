from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query, BackgroundTasks
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
from ..config import get_default_model_id
from ..models import Project, Segment, ProjectFile, ProjectFileCategory, GlossaryEntry, TranslationUnit
from ..logger import get_logger

logger = get_logger("ProjectRouter")

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
    background_tasks: BackgroundTasks,
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



    # Helper to process files
    from ..storage import upload_file, download_file

    async def process_files(file: UploadFile, category: ProjectFileCategory, project_id: str, db: Session):
        if not file.filename: return
        
        # Create unique object name
        # Format: {project_id}/{category}/{filename}
        object_name = f"{project_id}/{category.value}/{file.filename}"
        
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
            
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}", exc_info=True)
            # Log error but maybe continue?
            pass

    # Process all file categories
    for f in source_files or []:
        await process_files(f, ProjectFileCategory.source, new_project.id, db)
        
    for f in legal_files or []:
        await process_files(f, ProjectFileCategory.legal, new_project.id, db)
        
    for f in background_files or []:
        await process_files(f, ProjectFileCategory.background, new_project.id, db)
    
    db.commit()

    # Parse segments if we have a source docx
    # We find the source file record
    source_record = db.query(ProjectFile).filter(
        ProjectFile.project_id == new_project.id,
        ProjectFile.category == ProjectFileCategory.source.value,
        ProjectFile.filename.endswith(".docx")
    ).first()
    
    if source_record:
        temp_parse_path = os.path.join(UPLOAD_DIR, f"temp_{project_id}.docx")
        try:
            # Download from MinIO
            download_file(source_record.file_path, temp_parse_path)
            
            segments_internal = parse_docx(temp_parse_path, source_lang=source_lang)
            
            for i, seg_int in enumerate(segments_internal):
                seg_dump = seg_int.model_dump()
                db_segment = Segment(
                    id=seg_int.segment_id,
                    project_id=project_id,
                    index=i, # Force explicit order from list precedence
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

    # 5. Trigger RAG Ingestion (Background)
    # We use new session in background task
    if use_ai:
        from ..rag import ingest_project_files
        background_tasks.add_task(ingest_project_files, new_project.id)

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
            "tags": tags_data,
            "metadata": stored_meta.get("metadata"),
            "context_matches": stored_meta.get("context_matches")
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
        # Fallback to source if target is None OR empty string (Draft/Untranslated)
        if not target_text:
            target_text = db_seg.source_content 
        else:
            # Cleanup Tiptap HTML
            # Tiptap usually wraps in <p>...</p>. We are injecting into an existing w:p.
            # We want to remove the outer <p> tags.
            # Simple check for now.
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
    # Delete glossary entries manually (no cascade relationship)
    db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).delete()
    # Delete translation units manually (no cascade relationship)
    db.query(TranslationUnit).filter(TranslationUnit.project_id == project_id).delete()
    
    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}
    
# --- Segment Operations ---

@router.post("/segment/{segment_id}/generate-draft", response_model=SegmentResponse)
def generate_draft_endpoint(segment_id: str, mode: str = "translate", is_workflow: bool = False, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
        
    project = db.query(Project).filter(Project.id == segment.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get settings from project config
    config = project.config if project.config else {}
    ai_settings = config.get("ai_settings", {})
    threshold = float(ai_settings.get("similarity_threshold", 0.40))
    
    # Model Selection Strategy
    # Manual/Shortcuts -> "model" (default)
    # Workflows -> "workflow_model" (fallback to "model" if not set)
    default_model = ai_settings.get("model") or get_default_model_id()
    
    if is_workflow:
        model_name = ai_settings.get("workflow_model") or default_model
    else:
        model_name = default_model
    
    from ..rag import generate_segment_draft
    
    # Extract tags for Tab handling
    tags_data = None
    existing_matches = None
    if segment.metadata_json:
        tags_data = segment.metadata_json.get("tags")
        existing_matches = segment.metadata_json.get("context_matches")

    # If mode is 'analyze', we skip AI generation in RAG (we need to pass this down)
    # OR we handle it here by passing a flag to skip_generation?
    # Let's pass 'skip_ai' arg to generate_segment_draft
    skip_ai = (mode == "analyze")

    result = generate_segment_draft(
        segment_text=segment.source_content,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        project_id=str(project.id),
        db=db,
        threshold=threshold,
        model_name=model_name,
        tags=tags_data,
        cached_matches=existing_matches,
        skip_ai=skip_ai
    )
    
    if result.get("error"):
        error_msg = result["error"]
        logger.error(f"Draft generation failed: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {error_msg}")
    
    # Update Segment based on Mode
    
    # 1. Update Metadata (Always)
    current_meta = dict(segment.metadata_json or {})
    current_meta['context_matches'] = result["context_matches"]
    
    if mode == "translate":
        # Full Overwrite of Target
        segment.target_content = result["target_text"]
        current_meta['ai_draft'] = result["target_text"]
    
    elif mode == "draft":
        # Only save draft to metadata (suggestion)
        current_meta['ai_draft'] = result["target_text"]
        # Do NOT touch target_content
        
    elif mode == "analyze":
        # No draft generated (usually), just context matches updated
        pass

    segment.metadata_json = current_meta
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(segment, "metadata_json")
    
    db.commit()
    db.refresh(segment)
    
    resp_dict = segment.__dict__.copy()
    resp_dict['context_matches'] = result["context_matches"]
    
    # helper to extract json fields
    meta_json = segment.metadata_json or {}
    resp_dict['metadata'] = meta_json.get("metadata")
    resp_dict['tags'] = meta_json.get("tags")
    
    return resp_dict

@router.post("/{project_id}/reingest")
async def reingest_project_endpoint(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Triggers a full re-ingestion of the project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    from ..rag import reingest_project
    background_tasks.add_task(reingest_project, project_id)
    
    return {"message": "Re-ingestion started"}

@router.post("/{project_id}/generate-drafts")
async def generate_drafts_endpoint(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Triggers batch AI draft generation for all segments in the project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    from ..rag import generate_project_drafts
    background_tasks.add_task(generate_project_drafts, project_id)
    
    return {"message": "Batch draft generation started. This may take a while."}

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

# TMX Export Logic
def generate_tmx_content(source_lang, target_lang, segments):
    """
    Generates a TMX 1.4b compliant string from segments.
    """
    import datetime
    from xml.sax.saxutils import escape

    tmx_header = f"""<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4b">
  <header creationtool="Logion2" creationtoolversion="1.0"
          datatype="PlainText" segtype="sentence"
          adminlang="en-US" srclang="{source_lang}"
          o-tmf="Logion2TM"
          creationdate="{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}">
  </header>
  <body>"""

    tmx_body = ""
    for seg in segments:
        if not seg.target_content or not seg.source_content:
            continue
            
        # Strip internal tags for now? Or keep them?
        # TMX standard supports <bpt>, <ept>, <ph>. 
        # For simplicity, we might strip or just escape them as text if not strictly TMX tagged.
        # Let's clean tags for basic TMX to ensure compatibility with standard tools.
        # Or better: Just escape everything as text.
        
        src_clean = escape(seg.source_content)
        tgt_clean = escape(seg.target_content)

        tmx_body += f"""
    <tu>
      <tuv xml:lang="{source_lang}">
        <seg>{src_clean}</seg>
      </tuv>
      <tuv xml:lang="{target_lang}">
        <seg>{tgt_clean}</seg>
      </tuv>
    </tu>"""

    tmx_footer = """
  </body>
</tmx>"""
    
    return tmx_header + tmx_body + tmx_footer

@router.get("/{project_id}/export/tmx")
async def export_project_tmx(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")
    
    segments = db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
    
    tmx_content = generate_tmx_content(project.source_lang, project.target_lang, segments)
    
    output_filename = f"{project.filename}.tmx"
    output_path = os.path.join(UPLOAD_DIR, output_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tmx_content)
        
    return FileResponse(output_path, media_type="application/xml", filename=output_filename)
