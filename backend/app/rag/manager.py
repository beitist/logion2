import logging
from sqlalchemy.orm import Session
from typing import Optional, List, Dict

from .types import GenerationResult
from .retrieval import RetrievalEngine
from .assembly import ContextAssembler
from .inference import InferenceOrchestrator
from ..models import Segment

logger = logging.getLogger("RAG")

class RAGManager:
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.assembler = ContextAssembler(project_id, db)
        self.orchestrator = InferenceOrchestrator()
        
    async def generate_draft(
        self,
        segment: Segment, 
        source_lang: str, 
        target_lang: str,
        model_name: str = None, 
        custom_prompt: str = "",
        skip_ai: bool = False
    ) -> GenerationResult:
        """
        Main entry point for generating a draft.
        """
        # 1. Assemble Context
        # Note: assemble_context is synchronous (DB calls). 
        # In a fully async strict app, we should make DB calls async, but SQLAlchemy here is Sync by default.
        # Wrapping it in partial async if needed, but for now blocking on DB is standard in FastAPI sync routes.
        # But we are moving to async 'def'.
        # Blocking DB calls in async def is BAD. 
        # Ideally we run this in a thread executor if adhering to strict async.
        # Or we assume the latency is low enough.
        # Given "Async-Everything", we should wrap the Sync DB work.
        
        import asyncio
        loop = asyncio.get_event_loop()
        
        context = await loop.run_in_executor(None, lambda: self.assembler.assemble_context(segment))
        
        # 2. Check for Exact Match (Pre-Translation)
        exact_match = next((m for m in context.matches if m.score >= 100 and m.type != "glossary"), None)
        
        if exact_match:
            return GenerationResult(
                target_text=exact_match.content,
                context_used=context,
                is_exact=True
            )
            
        if skip_ai:
             return GenerationResult(
                target_text="",
                context_used=context
             )
        
        # 3. Inference
        result = await self.orchestrator.generate_draft(
            source_text=segment.source_content,
            source_lang=source_lang,
            target_lang=target_lang,
            context=context,
            model_name=model_name,
            custom_prompt=custom_prompt
        )
        
        return result

# --- Public API Facade ---

async def generate_segment_draft(
    segment_text: str, # Legacy Signature Argument (compatibility) - BUT we need Segment Object for ID
    project_id: str,
    db: Session,
    source_lang: str = "en", 
    target_lang: str = "de",
    threshold=0.4, 
    model_name=None, 
    custom_prompt="", 
    tags=None, 
    cached_matches=None, 
    skip_ai=False, 
    prev_context=None, 
    next_context=None
):
    """
    Facade function matching the conceptual signature of the old one, roughly.
    BUT: The new architecture relies on `Segment` object index for history/neighbors.
    The old one accepted raw strings and loose context lists.
    
    To support the Router's call which queries `Segment` first, we should ideally change the signature 
    to accept `segment_id`.
    
    HOWEVER, `project.py` calls it with `segment_text=segment.source_content`.
    Current `project.py`:
    
    result = generate_segment_draft(
            segment_text=segment.source_content,
            ...
            cached_matches=...
            prev_context=...
    )
    
    PROBLEM: We need the `Segment` object to get its Index for our new Assembler.
    If we only get text, we can't find its neighbors reliably without querying DB by text (unreliable).
    
    SOLUTION: We will update `project.py` to pass the `Segment` object or ID?
    Or we fetch it here using text (risky if duplicates)?
    Best: Update `project.py` to pass `segment_id` or the `segment` object.
    
    I will update the signature in `project.py` call.
    For this implementation, I'll add `segment_id` as an optional kwarg or 
    try to look it up.
    
    Actually, let's keep the signature in `__init__.py` clean and change `project.py`.
    Facade: `generate_segment_draft(segment_id: str, ...)`
    """
    pass # Implemented in __init__
