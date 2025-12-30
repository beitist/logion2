
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse, ProjectUpdate, ProjectListResponse, BatchTranslateRequest
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
    # Pydantic automatic mapping works because Segment model has 
    # properties for tags, metadata, context_matches
    return service.get_segments(project_id)

@router.post("/{project_id}/reinitialize", response_model=ProjectResponse)
def reinitialize_project(project_id: str, service: SegmentService = Depends(get_segment_service)):
    """
    Re-parses the source file but preserves existing translations.
    """
    return service.reinitialize_project(project_id)

@router.post("/segment/{segment_id}/generate-draft", response_model=SegmentResponse)
async def generate_draft_endpoint(
    segment_id: str, 
    mode: str = "translate", 
    is_workflow: bool = False, 
    force_refresh: bool = False,
    service: SegmentService = Depends(get_segment_service)
):
    """
    Triggers AI draft generation for a specific segment.
    Delegates all logic to SegmentService.
    """
    return await service.generate_and_log_draft(
        segment_id=segment_id, 
        mode=mode, 
        is_workflow=is_workflow, 
        force_refresh=force_refresh
    )

@router.post("/{project_id}/reingest")
async def reingest_project_endpoint(
    project_id: str, 
    background_tasks: BackgroundTasks, 
    service: ProjectService = Depends(get_project_service)
):
    """
    Triggers a full re-ingestion of the project.
    """
    service.trigger_reingestion(project_id, background_tasks)
    return {"message": "Re-ingestion started"}

@router.post("/{project_id}/generate-drafts")
async def generate_drafts_endpoint(
    project_id: str, 
    background_tasks: BackgroundTasks, 
    service: ProjectService = Depends(get_project_service)
):
    """
    Triggers batch AI draft generation for all segments in the project.
    """
    service.trigger_draft_generation(project_id, background_tasks)
    return {"message": "Batch draft generation started. This may take a while."}

@router.post("/{project_id}/workflow/copy-source")
async def copy_source_workflow(project_id: str, service: SegmentService = Depends(get_segment_service)):
    """
    Workflow: Bulk copy all source content to target content for a project.
    """
    service.bulk_copy_source_to_target(project_id)
    return {"message": "Copy source completed successfully", "project_id": project_id}


@router.post("/{project_id}/batch-translate")
async def batch_translate(
    project_id: str, 
    payload: BatchTranslateRequest,
    service: SegmentService = Depends(get_segment_service)
):
    """
    Translates a batch of segments (Synchronous).
    """
    return await service.process_batch_translation(project_id, payload.segment_ids, payload.mode)

@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, 
    payload: ProjectUpdate, 
    service: ProjectService = Depends(get_project_service)
):
    """
    Update project metadata (e.g. config/instructions).
    """
    return service.update_project(project_id, payload.dict(exclude_unset=True))

# --- Export Operations ---

@router.get("/{project_id}/export")
def export_project(project_id: str, service: ExportService = Depends(get_export_service)):
    return service.export_project(project_id)

@router.get("/{project_id}/export/tmx")
async def export_project_tmx(project_id: str, service: ExportService = Depends(get_export_service)):
    return service.export_project_tmx(project_id)
