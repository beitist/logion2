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

    async def generate_batch_draft(
        self,
        segment_ids: List[str],
        source_lang: str,
        target_lang: str,
        model_name: str = None,
        custom_prompt: str = ""
    ) -> Dict[str, GenerationResult]:
        """
        Batch Generation Logic.
        1. Retrieve/Assemble Context for all segments (Sync/Async wrap).
        2. Filter Exact Matches.
        3. Send remaining to Batch Inference.
        4. Merge results.
        """
        results = {}
        batch_payload = []
        batch_map = {} # map id -> context
        
        # 1. Assemble Context (Loop or Parallel)
        # We need segment objects first
        segments = self.db.query(Segment).filter(Segment.id.in_(segment_ids)).all()
        seg_map = {s.id: s for s in segments}
        
        # We re-order based on input list to maintain logic? Not strictly needed for dict result.
        
        import asyncio
        loop = asyncio.get_event_loop()
        
        for seg_id in segment_ids:
            seg = seg_map.get(seg_id)
            if not seg: continue
            
            # Assemble Context (Blocking DB)
            ctx = await loop.run_in_executor(None, lambda: self.assembler.assemble_context(seg))
            
            # Check Exact Match
            exact_match = next((m for m in ctx.matches if m.score >= 100 and m.type != "glossary"), None)
            
            if exact_match:
                results[seg_id] = GenerationResult(
                    target_text=exact_match.content,
                    context_used=ctx,
                    is_exact=True
                )
            else:
                # Prepare for Batch Inference
                # Serialize Context for Prompt
                ctx_str = ""
                if ctx.matches:
                    ctx_str += "TM:\n" + "\n".join([f"- {m.source_text} -> {m.content}" for m in ctx.matches[:3]])
                gloss_str = ""
                if ctx.glossary_hits:
                    gloss_str += "Glossary:\n" + "\n".join([f"- {g.source_text} -> {g.content}" for g in ctx.glossary_hits])
                
                payload_item = {
                    "id": seg_id,
                    "source": seg.source_content,
                    "context": ctx_str,
                    "glossary": gloss_str
                }
                batch_payload.append(payload_item)
                batch_map[seg_id] = ctx
                
        # 2. Batch Inference
        if batch_payload:
            translations, usage = await self.orchestrator.generate_batch(
                batch_payload, source_lang, target_lang, model_name, custom_prompt
            )
            
            # Distribute Usage? Simplified: Assign total to first or average? 
            # We'll attach full usage to a "batch" log or split it.
            # Splitting effectively is hard. We assign 0 to individual and handle bulk logging in service.
            
            for seg_id, target_text in translations.items():
                results[seg_id] = GenerationResult(
                    target_text=target_text,
                    context_used=batch_map.get(seg_id),
                    usage=usage if seg_id == batch_payload[0]['id'] else {} # Hack: Attach usage to first item for logging
                )
                
        return results

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
