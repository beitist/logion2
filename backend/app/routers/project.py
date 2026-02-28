from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Form, Depends, HTTPException, BackgroundTasks, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db
from ..schemas import ProjectCreate, ProjectResponse, SegmentResponse, ProjectUpdate, ProjectListResponse, BatchTranslateRequest


class TCDraftParams(BaseModel):
    tc_source_text: str
    tc_base_translation: str = ""
    tc_author_id: str = "mt"
    tc_author_name: str = "MT"
    tc_date: str = ""
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
async def reinitialize_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None),
    service: SegmentService = Depends(get_segment_service)
):
    """
    Re-parses the source file but preserves existing translations.
    Optionally accepts a new source file to replace the existing one.
    """
    return service.reinitialize_project(project_id, background_tasks, file)

@router.post("/segment/{segment_id}/generate-draft", response_model=SegmentResponse)
async def generate_draft_endpoint(
    segment_id: str,
    mode: str = "translate",
    is_workflow: bool = False,
    force_refresh: bool = False,
    tc_params: Optional[TCDraftParams] = Body(None),
    service: SegmentService = Depends(get_segment_service)
):
    """
    Triggers AI draft generation for a specific segment.
    If tc_params is provided, translates the TC stage source text
    and diffs against the base translation to produce TC markup.
    """
    return await service.generate_and_log_draft(
        segment_id=segment_id,
        mode=mode,
        is_workflow=is_workflow,
        force_refresh=force_refresh,
        tc_params=tc_params
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
@router.post("/{project_id}/preload-matches")
async def preload_matches_endpoint(
    project_id: str, 
    background_tasks: BackgroundTasks, 
    service: ProjectService = Depends(get_project_service)
):
    """
    Triggers background preloading of TM/Glossary matches for all segments.
    """
    service.trigger_preload_matches(project_id, background_tasks)
    return {"message": "Preload matches started."}
@router.post("/{project_id}/workflow/copy-source")
async def copy_source_workflow(project_id: str, service: SegmentService = Depends(get_segment_service)):
    """
    Workflow: Bulk copy all source content to target content for a project.
    """
    service.bulk_copy_source_to_target(project_id)
    return {"message": "Copy source completed successfully", "project_id": project_id}

@router.post("/{project_id}/workflow/clear-drafts")
async def clear_drafts_workflow(project_id: str, db: Session = Depends(get_db)):
    """
    Workflow: Clear all draft targets and AI metadata for unconfirmed segments.
    Use when drafts were generated with wrong MT model.
    """
    from ..workflows.clear_drafts import ClearDraftsWorkflow
    wf = ClearDraftsWorkflow(db, project_id)
    wf.run()
    return {"message": "Draft targets cleared successfully", "project_id": project_id}


class SequentialTranslateRequest(BaseModel):
    segment_ids: Optional[List[str]] = None

@router.post("/{project_id}/sequential-translate")
async def sequential_translate(
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: SequentialTranslateRequest,
    db: Session = Depends(get_db)
):
    """
    Sequential 1-by-1 translation with auto-glossary extraction after each segment.
    Higher quality than batch MT because terminology builds up incrementally.
    Accepts optional segment_ids to limit scope (e.g. file-filtered).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.rag_status == "processing":
        raise HTTPException(status_code=409, detail="A workflow is already running for this project")

    from ..workflows.sequential_translate import run_background_sequential_translate
    background_tasks.add_task(run_background_sequential_translate, project_id, payload.segment_ids)
    return {"status": "started", "message": "Sequential translation started in background"}

@router.post("/{project_id}/reset-workflow-status")
async def reset_workflow_status(project_id: str, db: Session = Depends(get_db)):
    """
    Resets a stuck workflow status back to 'ready'.
    Use when a workflow crashes and leaves the project in 'processing' state.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.rag_status = "ready"
    project.rag_progress = 100
    db.commit()
    return {"status": "reset", "message": "Workflow status reset to ready"}

@router.post("/{project_id}/batch-translate")
async def batch_translate(
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: BatchTranslateRequest,
    service: SegmentService = Depends(get_segment_service)
):
    """
    Translates a batch of segments (Asynchronous Background Task).
    """
    return service.process_batch_translation(project_id, background_tasks, payload.segment_ids, payload.mode)

@router.post("/{project_id}/tc-batch-translate")
async def tc_batch_translate(
    project_id: str,
    background_tasks: BackgroundTasks,
    service: SegmentService = Depends(get_segment_service)
):
    """
    TC Step-by-Step: Translates revision stages and generates TC markup.
    Processes all TC segments in the project.
    """
    return service.process_tc_batch(project_id, background_tasks)

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

# =========================================================================
# File Management Endpoints (Multi-File Support)
# =========================================================================

@router.get("/{project_id}/files", response_model=List[dict])
def get_project_files(project_id: str, service: ProjectService = Depends(get_project_service)):
    """
    Returns all files for a project with their metadata.
    """
    files = service.get_project_files(project_id)
    return [{
        "id": f.id,
        "filename": f.filename,
        "category": f.category,
        "uploaded_at": f.uploaded_at.isoformat(),
        "segment_count": len(f.segments) if hasattr(f, 'segments') else 0
    } for f in files]

@router.post("/{project_id}/files")
async def add_project_file(
    project_id: str,
    background_tasks: BackgroundTasks,
    category: str = Form(...),
    file: UploadFile = File(...),
    service: ProjectService = Depends(get_project_service)
):
    """
    Adds a new file to an existing project.
    Category must be 'source', 'legal', or 'background'.
    Source files are parsed immediately.
    Legal/background files trigger RAG reingest.
    """
    result = await service.add_file(project_id, category, file, background_tasks)
    return {
        "message": f"File '{result.filename}' added successfully",
        "file_id": result.id,
        "category": result.category
    }

@router.put("/{project_id}/files/{file_id}")
async def replace_project_file(
    project_id: str,
    file_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    service: ProjectService = Depends(get_project_service)
):
    """
    Replaces an existing file with a new version.
    For source files: old segments are deleted and new ones created.
    For legal/background: triggers RAG reingest.
    """
    result = await service.replace_file(project_id, file_id, file, background_tasks)
    return {
        "message": f"File replaced with '{result.filename}'",
        "file_id": result.id
    }

@router.delete("/{project_id}/files/{file_id}")
def delete_project_file(
    project_id: str,
    file_id: str,
    service: ProjectService = Depends(get_project_service)
):
    """
    Deletes a file and all its linked segments.
    """
    return service.delete_file(project_id, file_id)

