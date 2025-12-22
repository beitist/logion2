
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse, ProjectUpdate, ProjectListResponse
from ..models import Project, Segment, ProjectFile, ProjectFileCategory, AiUsageLog
from ..logger import get_logger
from ..config import get_default_model_id

# Services
from ..services.project_service import ProjectService
from ..services.segment_service import SegmentService
from ..services.export_service import ExportService

logger = get_logger("ProjectRouter")
router = APIRouter(prefix="/project", tags=["project"])

# Dependency Helpers
def get_project_service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(db)

def get_segment_service(db: Session = Depends(get_db)) -> SegmentService:
    return SegmentService(db)

def get_export_service(db: Session = Depends(get_db)) -> ExportService:
    return ExportService(db)

@router.get("/", response_model=List[ProjectListResponse])
def get_projects(service: ProjectService = Depends(get_project_service)):
    """
    Returns a list of all projects.
    """
    return service.get_all_projects()

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
    service: ProjectService = Depends(get_project_service)
):
    """
    Creates a new project with multiple files and settings.
    Parses the first valid source DOCX for segments.
    """
    return await service.create_project(
        name=name,
        source_lang=source_lang,
        target_lang=target_lang,
        use_ai=use_ai,
        background_tasks=background_tasks,
        source_files=source_files,
        legal_files=legal_files,
        background_files=background_files
    )

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, service: ProjectService = Depends(get_project_service)):
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.delete("/{project_id}")
async def delete_project(project_id: str, service: ProjectService = Depends(get_project_service)):
    """
    Deletes a project and all associated segments.
    """
    service.delete_project(project_id)
    return {"message": "Project deleted successfully"}

@router.post("/{project_id}/duplicate", response_model=ProjectResponse)
def duplicate_project(project_id: str, service: ProjectService = Depends(get_project_service)):
    """
    Creates a deep copy of the project.
    """
    return service.duplicate_project(project_id)

# --- Segment Operations ---

@router.get("/{project_id}/segments", response_model=List[SegmentResponse])
def get_project_segments(project_id: str, service: SegmentService = Depends(get_segment_service)):
    segments = service.get_segments(project_id)
    
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

@router.post("/{project_id}/reinitialize", response_model=ProjectResponse)
def reinitialize_project(project_id: str, service: SegmentService = Depends(get_segment_service)):
    """
    Re-parses the source file but preserves existing translations.
    """
    return service.reinitialize_project(project_id)

@router.post("/segment/{segment_id}/generate-draft", response_model=SegmentResponse)
async def generate_draft_endpoint(segment_id: str, mode: str = "translate", is_workflow: bool = False, force_refresh: bool = False, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
        
    project = db.query(Project).filter(Project.id == segment.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # If mode is 'copy_source' (Verification Workflow)
    # Check this FIRST to avoid loading RAG/AI models
    if mode == "copy_source":
         import datetime
         # Direct Copy: Bypass RAG
         segment.target_content = segment.source_content
         segment.status = "translated"
         
         # Safe Metadata Update
         md = dict(segment.metadata_json) if segment.metadata_json else {}
         md["last_modified"] = datetime.datetime.utcnow().isoformat()
         segment.metadata_json = md
         
         db.commit()
         db.refresh(segment)
         
         return SegmentResponse(
             id=segment.id,
             index=segment.index,
             source_content=segment.source_content,
             target_content=segment.target_content,
             status=segment.status,
             project_id=segment.project_id,
             context_matches=[]
         )

    # Get settings from project config
    config = project.config if project.config else {}
    ai_settings = config.get("ai_settings", {})
    threshold = float(ai_settings.get("similarity_threshold", 0.40))
    
    default_model = ai_settings.get("model") or get_default_model_id()
    
    if is_workflow:
        model_name = ai_settings.get("workflow_model") or default_model
    else:
        model_name = default_model

    custom_prompt = ai_settings.get("custom_prompt", "")
    
    # If mode is 'analyze', we skip AI generation in RAG
    skip_ai = (mode == "analyze")

    # Use New RAG Manager V2 (Async & Encapsulated)
    from ..rag import generate_segment_draft_v2
    
    try:
        result_dict = await generate_segment_draft_v2(
            segment_id=segment.id,
            project_id=str(project.id),
            db=db,
            model_name=model_name,
            custom_prompt=custom_prompt,
            skip_ai=skip_ai
        )
        
        # Adaptation for Router Response
        target_text = result_dict.get("target_text", "")
        context_used = result_dict.get("context_used", {})
        context_matches = context_used.get("matches", [])
        usage = result_dict.get("usage", {})
        error = result_dict.get("error")
        
        if error:
            logger.error(f"Draft generation failed: {error}")
            raise HTTPException(status_code=500, detail=f"Analysis failed: {error}")
        
        # Update Segment based on Mode
        
        # 1. Update Metadata (Always)
        current_meta = dict(segment.metadata_json or {})
        current_meta['context_matches'] = context_matches
        
        if mode == "translate":
            # Full Overwrite of Target
            segment.target_content = target_text
            current_meta['ai_draft'] = target_text
        
        elif mode == "draft":
            # Only save draft to metadata (suggestion)
            current_meta['ai_draft'] = target_text
            # Do NOT touch target_content
            
        elif mode == "analyze":
            # No draft generated (usually), just context matches updated
            pass
            
        # Track Token Usage (DB Logging)
        if usage:
            new_log = AiUsageLog(
                project_id=project.id,
                segment_id=segment.id,
                model=model_name,
                trigger_type="generation",
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0)
            )
            db.add(new_log)
            
            # Update Aggregate Config (for UI)
            current_config = dict(project.config or {})
            usage_stats = current_config.get("usage_stats", {})
            model_stats = usage_stats.get(model_name, {"input_tokens": 0, "output_tokens": 0})
            
            model_stats["input_tokens"] += usage.get("input_tokens", 0)
            model_stats["output_tokens"] += usage.get("output_tokens", 0)
            
            usage_stats[model_name] = model_stats
            current_config["usage_stats"] = usage_stats
            project.config = current_config
            flag_modified(project, "config")
            
        # Store Model Used in Metadata
        current_meta['ai_model'] = model_name

        segment.metadata_json = current_meta
        flag_modified(segment, "metadata_json")
        
        db.commit()
        db.refresh(segment)
        
        resp_dict = segment.__dict__.copy()
        resp_dict['context_matches'] = context_matches
        
        meta_json = segment.metadata_json or {}
        resp_dict['metadata'] = meta_json.get("metadata")
        resp_dict['tags'] = meta_json.get("tags")
        
        return resp_dict
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Generate Draft Endpoint Error: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

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

@router.post("/{project_id}/workflow/copy-source")
async def copy_source_workflow(project_id: str, db: Session = Depends(get_db)):
    """
    Workflow: Bulk copy all source content to target content for a project.
    Efficient SQL implementation.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        db.query(Segment).filter(Segment.project_id == project_id).update(
            {
                Segment.target_content: Segment.source_content,
                Segment.status: "translated",
            },
            synchronize_session=False
        )
        db.commit()
        
        return {"message": "Copy source completed successfully", "project_id": project_id}
    except Exception as e:
        db.rollback()
        logger.error(f"Bulk copy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

# --- Export Operations ---

@router.get("/{project_id}/export")
def export_project(project_id: str, service: ExportService = Depends(get_export_service)):
    return service.export_project(project_id)

@router.get("/{project_id}/export/tmx")
async def export_project_tmx(project_id: str, service: ExportService = Depends(get_export_service)):
    return service.export_project_tmx(project_id)
