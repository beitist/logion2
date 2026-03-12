import logging
import asyncio
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any, Tuple

from .types import GenerationResult, TranslationMatch, SegmentContext
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
        
        # Inject Retrieval Usage from Context
        result.retrieval_usage = context.retrieval_usage
        
        return result

    async def generate_batch_draft(
        self,
        segment_ids: List[str],
        source_lang: str,
        target_lang: str,
        model_name: str = None,
        custom_prompt: str = "",
        skip_ai: bool = False
    ) -> Tuple[Dict[str, GenerationResult], Dict[str, int]]:
        """
        Batch Generation with Windowed Context.
        Returns: (Results Dict, Usage Dict {input_tokens, output_tokens})
        """
        results = {}
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        
        # 1. Fetch Segments & Sort
        segments = self.db.query(Segment).filter(Segment.id.in_(segment_ids)).order_by(Segment.index).all()
        if not segments:
            return {}, total_usage
            
        seg_map = {s.id: s for s in segments}
        sorted_segments = segments # Already sorted by index
        
        first_seg = sorted_segments[0]
        last_seg = sorted_segments[-1]
        
        loop = asyncio.get_event_loop()

        # 2. Assemble Windowed Context (Rich)
        # Global Preceding: Before the FIRST segment (Include Translation)
        # Global Following: After the LAST segment (Source Only)
        
        def get_rich_preceding(idx, limit=3):
            segs = self.db.query(Segment).filter(
                Segment.project_id == self.project_id,
                Segment.index < idx
            ).order_by(Segment.index.desc()).limit(limit).all()
            
            # Reorder to reading flow (asc)
            segs.reverse()
            
            out = []
            for s in segs:
                if s.target_content:
                    out.append(f"{s.source_content} [Trans: {s.target_content}]")
                else:
                    out.append(s.source_content)
            return out

        preceding_ctx = await loop.run_in_executor(None, lambda: get_rich_preceding(first_seg.index, 3))
        
        following_ctx = await loop.run_in_executor(
            None, 
            lambda: self.assembler.get_source_neighbors(last_seg.index, 1, 3)
        )
        
        # 3. Prepare Batch Items
        # Optimization: Reuse existing context_matches from metadata if available
        # This saves retrieval/reranking API costs and maintains consistency with UI
        batch_items = []
        context_map = {} 
        
        for seg in sorted_segments:
            # Check if segment already has context_matches in metadata
            # These are pre-computed during "Analyze" or "Pre-Translate" workflows
            existing_matches = None
            existing_glossary = []
            
            if seg.metadata_json and seg.metadata_json.get("context_matches"):
                # Reuse existing hits - reconstruct SegmentContext from stored data
                # Filter out the MT hit (type='mt') as that's the previous translation
                stored_hits = seg.metadata_json.get("context_matches", [])
                
                # Reconstruct TranslationMatch objects from stored dicts
                reused_matches = []
                for hit in stored_hits:
                    if hit.get("type") == "mt":
                        continue  # Skip previous MT results
                    try:
                        reused_matches.append(TranslationMatch(
                            id=hit.get("id", ""),
                            content=hit.get("content", ""),
                            source_text=hit.get("source_text"),
                            filename=hit.get("filename", "Unknown"),
                            type=hit.get("type", "optional"),
                            category=hit.get("category", "background"),
                            score=hit.get("score", 0),
                            note=hit.get("note")
                        ))
                    except Exception as e:
                        # Log malformed hits so we can diagnose serialization issues.
                        # Previously this was a silent pass, hiding potential bugs.
                        logger.warning(f"Skipping malformed context_match entry for segment {seg.id}: {e} | hit={hit}")
                
                if reused_matches:
                    existing_matches = reused_matches
                    # Separate glossary hits from regular matches
                    existing_glossary = [m for m in existing_matches if m.type == "glossary"]
                    existing_matches = [m for m in existing_matches if m.type != "glossary"]
                    logger.info(f"Segment {seg.id}: Reusing {len(existing_matches)} existing matches + {len(existing_glossary)} glossary hits")
            
            # If we have existing matches, use them; otherwise do fresh retrieval
            if existing_matches is not None:
                # Build context from existing matches (no API calls)
                ctx = SegmentContext(
                    matches=existing_matches,
                    glossary_hits=existing_glossary,
                    retrieval_usage={}  # No retrieval cost - reused!
                )
            else:
                # Fresh retrieval (expensive - involves embedding + reranking)
                ctx = await loop.run_in_executor(None, lambda seg=seg: self.assembler.assemble_context(seg))
            
            # Check Exact Match Early (100% TM match)
            exact = next((m for m in ctx.matches if m.score >= 100 and m.type != "glossary"), None)
            if exact:
                 results[seg.id] = GenerationResult(
                     target_text=exact.content,
                     context_used=ctx,
                     is_exact=True
                 )
                 continue
            
            context_map[seg.id] = ctx
            
            # Format Matches for LLM prompt - Exclude 'history' as it is covered by Global Preceding Context
            tm_matches = [{"source": m.source_text, "target": m.content, "score": m.score} 
                          for m in ctx.matches[:3] 
                          if m.type not in ['glossary', 'history'] and m.score < 100]
                          
            glossary = [
                {"term": g.source_text, "translation": g.content,
                 **({"note": g.note} if g.note else {})}
                for g in ctx.glossary_hits
            ]
            
            batch_items.append({
                "id": seg.id,
                "source_text": seg.source_content,
                "tm_matches": tm_matches,
                "glossary_matches": glossary
            })
            
        # 4. Inference (skip when analyze-only)
        if batch_items and skip_ai:
            # Analyze mode: return context without LLM inference
            for item in batch_items:
                sid = item['id']
                results[sid] = GenerationResult(
                    target_text="",
                    context_used=context_map.get(sid),
                    retrieval_usage=context_map.get(sid).retrieval_usage if context_map.get(sid) else {}
                )
        elif batch_items:
            translations, batch_usage = await self.orchestrator.generate_structured_batch(
                preceding_context=preceding_ctx,
                following_context=following_ctx,
                batch_items=batch_items,
                source_lang=source_lang,
                target_lang=target_lang,
                model_name=model_name,
                custom_prompt=custom_prompt
            )

            total_usage["input_tokens"] += batch_usage.get("input_tokens", 0)
            total_usage["output_tokens"] += batch_usage.get("output_tokens", 0)

            # Merge Results
            for item in batch_items:
                sid = item['id']
                if sid in translations:
                    results[sid] = GenerationResult(
                        target_text=translations[sid],
                        context_used=context_map.get(sid),
                        usage={}, # Usage tracked globally for batch
                        retrieval_usage=context_map.get(sid).retrieval_usage if context_map.get(sid) else {}
                    )
                else:
                    results[sid] = GenerationResult(
                        target_text="",
                        context_used=context_map.get(sid),
                        error="Missing from AI response"
                    )

        return results, total_usage
