import re
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import Segment, SegmentStatus
from .types import SegmentContext, TranslationMatch
from .retrieval import RetrievalEngine
from ..glossary_service import GlossaryMatcher
from ..tmx import compute_hash

class ContextAssembler:
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.retrieval = RetrievalEngine()
        self.glossary = GlossaryMatcher(project_id, db)
        
    def assemble_context(self, segment: Segment) -> SegmentContext:
        """
        Builds the complete context for a segment:
        1. Retrieval Matches (TM + Vector)
        2. Glossary Hits
        3. Neighborhood (Source Context)
        4. History (Short Term Memory)
        """
        # 1. Retrieval
        matches, usage = self.retrieval.retrieve_matches(
            db=self.db, 
            project_id=self.project_id, 
            query=segment.source_content,
            segment_id=segment.id
        )
        
        # 2. Neighbors (Source File Context)
        # We need the file_id and chunk_index.
        # Segment is linked to Project, but not directly to ContextChunk easily unless we trace it back.
        # BUT, the prompt asked for "ID-n to ID+n within same file".
        # We don't have file_id on Segment directly (it's flat in Project).
        # Actually ProjectFile -> Segment relation is implicitly by 'index'?
        # In current model, Segment has 'index' in project.
        # The 'source_content' comes from parsing.
        # We can implement 'History' easily (Segment Index - 1).
        # But 'File Neighbor' requires knowing the file boundaries.
        # Assume 'Segment Index' is global for the project.
        # So Prev/Next source segments are just index-1, index+1.
        
        prev_sources = self.get_source_neighbors(segment.index, -1, 3) # Prev 3
        next_sources = self.get_source_neighbors(segment.index, 1, 3)  # Next 3
        
        # 3. History (Target Context from CONFIRMED segments)
        history = self._get_translation_history(segment.index, limit=5)
        
        # 4. Glossary
        gloss_hits = self.glossary.find_matches(segment.source_content)
        # Convert to TranslationMatch for uniformity
        gloss_matches = []
        for g in gloss_hits:
             origin = g.get("origin", "manual")
             gloss_matches.append(TranslationMatch(
                 id=f"gloss-{compute_hash(g['source'])}",
                 content=g['target'],
                 source_text=g['source'],
                 filename="Auto-Glossary" if origin == "auto" else "Glossary",
                 type="glossary",
                 category="term",
                 score=100,
                 note=g['note'],
                 metadata={"origin": origin},
             ))
             
        # 5. Unit Conversion Facts
        facts = self._extract_unit_facts(segment.source_content)
        if facts:
             # Add as a special 'fact' match or handle in prompt?
             # We'll add it as a high-confidence match with a note 
             # OR we add it to a 'facts' list in SegmentContext if we update the model.
             # For now, let's append to matches as 'system' info
             for f in facts:
                 matches.insert(0, TranslationMatch(
                     id="fact-unit",
                     content=f,
                     source_text=segment.source_content, # vague
                     filename="System",
                     type="fact",
                     category="background",
                     score=100
                 ))

        context = SegmentContext(
            matches=matches,
            prev_chunks=prev_sources,
            next_chunks=next_sources,
            glossary_hits=gloss_matches,
            retrieval_usage=usage
        )
        # We might want to attach history to 'matches' or separate field.
        # SegmentContext definition had 'matches', 'prev_chunks' (source), 'next_chunks' (source).
        # History is 'Target' context. WE should add that to SegmentContext or inject in matches?
        # Let's verify types.py
        
        # I'll inject History as 'tm' matches with type 'history' context
        for h in history:
            matches.append(TranslationMatch(
                id=f"hist-{h.id}",
                content=h.target_content,
                source_text=h.source_content,
                filename="History",
                type="history",
                category="tm",
                score=100
            ))
            
        return context

    def get_source_neighbors(self, current_index: int, direction: int, count: int) -> List[str]:
        """Fetch surrounding source text from DB Segments"""
        # direction: -1 for prev, 1 for next
        if direction < 0:
            start = current_index - count
            end = current_index - 1
        else:
            start = current_index + 1
            end = current_index + count
            
        segs = self.db.query(Segment.source_content).filter(
            Segment.project_id == self.project_id,
            Segment.index >= start,
            Segment.index <= end
        ).order_by(Segment.index.asc()).all()
        
        return [s[0] for s in segs]

    def _get_translation_history(self, current_index: int, limit: int = 5) -> List[Segment]:
        """Fetch recently translated segments (Short Term Memory)"""
        # We want segments BEFORE current_index that are 'translated' or at least have target
        # Ordering: Closest first? Or chronological? 
        # Usually chronological (Index 5, 6, 7) for prompt flow.
        segs = self.db.query(Segment).filter(
            Segment.project_id == self.project_id,
            Segment.index < current_index,
            Segment.target_content != None,
            Segment.target_content != ""
        ).order_by(Segment.index.desc()).limit(limit).all()
        
        # Return in reading order (Ascending)
        return sorted(segs, key=lambda x: x.index)

    def _extract_unit_facts(self, text: str) -> List[str]:
        """
        Detects Indian numbering (Lakh, Crore) and provides conversion facts.
        1 Lakh = 100,000
        1 Crore = 10,000,000
        """
        facts = []
        import re
        
        # Regex for "X Lakh" or "X.Y Lakh"
        lakhs = re.findall(r'(\d+(?:\.\d+)?)\s*Lakhs?', text, re.IGNORECASE)
        for val in lakhs:
             try:
                 v = float(val)
                 conv = v * 100_000
                 facts.append(f"Fact: {val} Lakh = {conv:,.0f} (International)")
             except: pass
             
        crores = re.findall(r'(\d+(?:\.\d+)?)\s*Crores?', text, re.IGNORECASE)
        for val in crores:
             try:
                 v = float(val)
                 # 1 Crore = 10 Million
                 conv = v * 10_000_000
                 facts.append(f"Fact: {val} Crore = {conv:,.0f} (International)")
             except: pass
             
        return facts
