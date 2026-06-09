from .manager import RAGManager
from .tasks import generate_project_drafts
from .retrieval import RetrievalEngine
from .types import GenerationResult
from sqlalchemy.orm import Session

async def generate_segment_draft_v2(
    segment_id: str,
    project_id: str,
    db: Session,
    model_name: str = None,
    custom_prompt: str = "",
    skip_ai: bool = False
) -> dict:
    
    from ..models import Segment
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise ValueError("Segment not found")
        
    manager = RAGManager(project_id, db)
    
    # We assume project source/target lang are in Project, but we can query them or accept args.
    # Manager doesn't query project lang yet.
    from ..models import Project
    project = db.query(Project).filter(Project.id == project_id).first()
    
    res = await manager.generate_draft(
        segment=segment,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        model_name=model_name,
        custom_prompt=custom_prompt,
        skip_ai=skip_ai
    )
    
    # Convert Pydantic to Dict for router compatibility
    return res.model_dump()
