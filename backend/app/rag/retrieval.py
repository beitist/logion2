import logging
import difflib
import re
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text, or_

from ..models import TranslationUnit, TranslationOrigin, ContextChunk, ProjectFile, ProjectFileCategory, Segment
from ..tmx import compute_hash, normalize_text
from .types import TranslationMatch
from sentence_transformers import SentenceTransformer, CrossEncoder
import numpy as np

logger = logging.getLogger("RAG.Retrieval")

class RetrievalEngine:
    _instance = None
    _bi_encoder = None
    _cross_encoder = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RetrievalEngine, cls).__new__(cls)
            cls._instance._load_models()
        return cls._instance

    def _load_models(self):
        # Force CPU as per legacy config to avoid MPS issues
        device = "cpu" 
        try:
            logger.info(f"Loading Models on {device}...")
            # 1. Bi-Encoder (LaBSE)
            self._bi_encoder = SentenceTransformer('sentence-transformers/LaBSE', device=device)
            # 2. Cross-Encoder (Reranking)
            self._cross_encoder = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', device=device)
            logger.info("✅ Retrieval Models Loaded.")
        except Exception as e:
            logger.error(f"❌ Error loading models: {e}", exc_info=True)

    def clean_tags(self, text: str) -> str:
        """Strips XML-like tags for embedding."""
        if not text: return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\[(TAB|COMMENT|SHAPE)\]', '', text)
        return text.strip()

    def get_neighbors(self, db: Session, file_id: str, chunk_index: int, window: int = 2) -> Tuple[List[str], List[str]]:
        """
        Retrieves ID-based neighbors (Prev, Next).
        Returns ([prev_texts], [next_texts])
        """
        if chunk_index is None:
            return [], []
            
        # Range: [index - window, index + window] excluding index
        min_idx = max(0, chunk_index - window)
        max_idx = chunk_index + window
        
        chunks = db.query(ContextChunk).filter(
            ContextChunk.file_id == file_id,
            ContextChunk.chunk_index >= min_idx,
            ContextChunk.chunk_index <= max_idx
        ).order_by(ContextChunk.chunk_index.asc()).all()
        
        prev_ctx = []
        next_ctx = []
        
        for c in chunks:
            if c.chunk_index < chunk_index:
                prev_ctx.append(c.content)
            elif c.chunk_index > chunk_index:
                next_ctx.append(c.content)
                
        return prev_ctx, next_ctx

    def retrieve_matches(self, db: Session, project_id: str, query: str, limit: int = 5, segment_id: str = None) -> List[TranslationMatch]:
        """
        Main retrieval pipeline:
        1. Exact/TM Lookup
        2. Vector Search (Hybrid)
        3. Reranking
        """
        matches = []
        
        # 1. Exact / Hash Lookup
        exact_matches = self._lookup_tm(db, project_id, query)
        matches.extend(exact_matches)
        
        # 2. Vector Search (if needed or for optional context)
        # Only search if we don't have a mandatory exact match? 
        # Actually user wants "ContextAssembler" to pick. We provide all candidates.
        vector_matches = self._search_vector_chunks(db, project_id, query, top_k=20, segment_id=segment_id)
        
        # 3. Rerank Vector Matches
        reranked = self._rerank(query, vector_matches)
        
        # Merge (Dedup by ID)
        seen_ids = set([m.id for m in matches])
        
        for cand in reranked:
            if cand.id not in seen_ids:
                matches.append(cand)
                seen_ids.add(cand.id)
                
        # Sort by Score
        matches.sort(key=lambda x: x.score, reverse=True)
        return matches[:limit]

    def _lookup_tm(self, db: Session, project_id: str, text_val: str) -> List[TranslationMatch]:
        results = []
        s_hash = compute_hash(text_val)
        
        tms = db.query(TranslationUnit).filter(
            TranslationUnit.project_id == project_id,
            TranslationUnit.source_hash == s_hash
        ).all()
        
        for tm in tms:
            # Score logic: Mandatory=100, User=99, Optional=95
            score = 95
            if tm.origin_type == TranslationOrigin.mandatory: score = 100
            elif tm.origin_type == TranslationOrigin.user: score = 99
            
            results.append(TranslationMatch(
                id=f"tm-{tm.id}",
                content=tm.target_text,
                source_text=tm.source_text,
                filename="Translation Memory",
                type=tm.origin_type,
                category="tm",
                score=score
            ))
        return results

    def _search_vector_chunks(self, db: Session, project_id: str, query: str, top_k: int = 30, segment_id: str = None) -> List[TranslationMatch]:
        if not self._bi_encoder: return []
        
        query_vec = None
        
        # Try to use pre-calculated Segment Vector
        if segment_id:
            seg = db.query(Segment).filter(Segment.id == segment_id).first()
            # Check if seg exists AND has embedding (must be list/array, not None)
            if seg and seg.embedding is not None:
                # pgvector returns numpy array or list? 
                # SQLAlchemy model usually returns list or string depending on driver.
                # Assuming list/numpy compatible.
                query_vec = seg.embedding
                # logger.info(f"Using pre-calculated vector for segment {segment_id}")

        # Fallback to Inference
        if query_vec is None:
            clean_query = self.clean_tags(query)
            try:
                query_vec = self._bi_encoder.encode(clean_query, normalize_embeddings=True).tolist()
            except:
                return []
            
        # Database Vector Search
        # Joining ProjectFile to filter by Project
        results = db.query(ContextChunk, ProjectFile)\
            .join(ProjectFile)\
            .filter(ProjectFile.project_id == project_id)\
            .order_by(ContextChunk.embedding.cosine_distance(query_vec))\
            .limit(top_k)\
            .all()
            
        matches = []
        for chunk, file in results:
            # Initial cosine score is implicit in order, but we can't easily get the float from pgvector query in ORM easily 
            # without custom select. 
            # We will rely on Reranker for the score. 
            # We assign a dummy candidate score.
            
            matches.append(TranslationMatch(
                id=chunk.id,
                content=chunk.rich_content or chunk.content,
                source_text=chunk.content, # The source chunk
                filename=file.filename,
                type="context", # refined later
                category=file.category,
                score=0, # Placeholder
                chunk_index=chunk.chunk_index,
                file_id=file.id
            ))
        return matches

    def _rerank(self, query: str, candidates: List[TranslationMatch]) -> List[TranslationMatch]:
        if not candidates or not self._cross_encoder: 
            return candidates
            
        pairs = [[query, c.source_text] for c in candidates]
        
        try:
            scores = self._cross_encoder.predict(pairs)
        except:
            return candidates
            
        for i, match in enumerate(candidates):
            # Sigmoid or just approximate mapping of logit to 0-100
            logit = float(scores[i])
            match.raw_logit = logit
            
            # Heuristic map: >3 is good match (~80%), >6 is excellent (~95%)
            # Using simple scaling for now.
            # 1 / (1 + exp(-x)) -> 0.0 to 1.0
            import math
            prob = 1 / (1 + math.exp(-logit))
            match.score = int(prob * 100)
            
            # Penalize 'optional' slightly (Business Rule)
            if match.category != ProjectFileCategory.legal:
                match.score = max(0, match.score - 5)
                
        # Filter low scores
        return [m for m in candidates if m.score > 40]
