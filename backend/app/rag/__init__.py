from .manager import RAGManager
from .ingestion import ingest_project_files
from .retrieval import RetrievalEngine
from .types import GenerationResult

# Legacy Support / Route Adapter
async def generate_segment_draft(
    segment_text: str,
    project_id: str,
    db: Session,
    source_lang: str = "en", 
    target_lang: str = "de",
    model_name=None, 
    custom_prompt="", 
    skip_ai=False,
    # These legacy args are now less relevant but kept to avoid kwargs errors if not cleaned
    threshold=0.4, 
    tags=None, 
    cached_matches=None, 
    prev_context=None, 
    next_context=None
):
    """
    Adapter function.
    We need to find the Segment object to use the new Assembler effectively.
    """
    from ..models import Segment
    
    # Try to find segment by text? 
    # This is fragile. We should ideally change the router to pass ID.
    # But since I'm updating the router anyway, I'll change the call there!
    # So I can change the signature here.
    
    raise DeprecationWarning("Use generate_segment_draft_v2 with segment_id")

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
    return res.dict()
