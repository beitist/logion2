import logging
import asyncio
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from .types import GenerationResult
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
        Main entry point for generating a draft (Single Segment).
        """
        # 1. Assemble Context (Blocking)
        loop = asyncio.get_event_loop()
        context = await loop.run_in_executor(None, lambda: self.assembler.assemble_context(segment))
        
        # 2. Check for Exact Match
        exact_match = next((m for m in context.matches if m.score >= 100 and m.type != "glossary"), None)
        
        if exact_match:
            return GenerationResult(
                target_text=exact_match.content,
                context_used=context,
                is_exact=True
            )
            
        if skip_ai:
             return GenerationResult(target_text="", context_used=context)
        
        # 3. Inference (Structured)
        # We pass segment_id for ID tracking in the batch-of-1
        result = await self.orchestrator.generate_draft(
            source_text=segment.source_content,
            source_lang=source_lang,
            target_lang=target_lang,
            context=context,
            model_name=model_name,
            custom_prompt=custom_prompt,
            segment_id=segment.id
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
        Batch Generation with Windowed Context.
        """
        results = {}
        
        # 1. Fetch Segments & Sort
        # We assume segment_ids are from the same project
        segments = self.db.query(Segment).filter(Segment.id.in_(segment_ids)).order_by(Segment.index).all()
        if not segments:
            return {}
            
        seg_map = {s.id: s for s in segments}
        sorted_segments = segments # Already sorted by index
        
        first_seg = sorted_segments[0]
        last_seg = sorted_segments[-1]
        
        # 2. Assemble Windowed Context
        # Global Preceding: Before the FIRST segment
        # Global Following: After the LAST segment
        
        loop = asyncio.get_event_loop()
        
        preceding_ctx = await loop.run_in_executor(
            None, 
            lambda: self.assembler.get_source_neighbors(first_seg.index, -1, 3)
        )
        
        following_ctx = await loop.run_in_executor(
            None, 
            lambda: self.assembler.get_source_neighbors(last_seg.index, 1, 3)
        )
        
        # 3. Prepare Batch Items (with specific context per item: Glossary + TM)
        batch_items = []
        context_map = {} # Store context objects to return later
        
        for seg in sorted_segments:
            # We still need full context for TM matches and Glossary
            ctx = await loop.run_in_executor(None, lambda: self.assembler.assemble_context(seg))
            
            # Check Exact Match Early
            exact = next((m for m in ctx.matches if m.score >= 100 and m.type != "glossary"), None)
            if exact:
                 results[seg.id] = GenerationResult(
                     target_text=exact.content,
                     context_used=ctx,
                     is_exact=True
                 )
                 continue
            
            context_map[seg.id] = ctx
            
            # Format Matches
            tm_matches = [{"source": m.source_text, "target": m.content, "score": m.score} 
                          for m in ctx.matches[:3] if m.type != 'glossary' and m.score < 100]
                          
            glossary = [{"term": g.source_text, "translation": g.content} 
                        for g in ctx.glossary_hits]
            
            batch_items.append({
                "id": seg.id,
                "source_text": seg.source_content,
                "tm_matches": tm_matches,
                "glossary_matches": glossary
            })
            
        # 4. Inference
        if batch_items:
            translations, usage = await self.orchestrator.generate_structured_batch(
                preceding_context=preceding_ctx,
                following_context=following_ctx,
                batch_items=batch_items,
                source_lang=source_lang,
                target_lang=target_lang,
                model_name=model_name,
                custom_prompt=custom_prompt
            )
            
            # Merge Results
            for item in batch_items:
                sid = item['id']
                if sid in translations:
                    results[sid] = GenerationResult(
                        target_text=translations[sid],
                        context_used=context_map.get(sid),
                        usage={} 
                    )
                else:
                    # Failed or Missing from response
                    results[sid] = GenerationResult(
                        target_text="",
                        context_used=context_map.get(sid),
                        error="Missing from AI response"
                    )
                    
        return results
