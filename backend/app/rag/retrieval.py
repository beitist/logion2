import logging
import difflib
import re
import os
import voyageai
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text, or_

from ..models import TranslationUnit, TranslationOrigin, ContextChunk, ProjectFile, ProjectFileCategory, Segment
from ..tmx import compute_hash, normalize_text
from .types import TranslationMatch
from sentence_transformers import CrossEncoder # Keep CrossEncoder for reranking!
import numpy as np

logger = logging.getLogger("RAG.Retrieval")

class RetrievalEngine:
    _instance = None
    _client = None
    _cross_encoder = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RetrievalEngine, cls).__new__(cls)
            cls._instance._load_models()
        return cls._instance

    def _load_models(self):
        try:
            logger.info("Loading Retrieval Models...")
            
            # 1. Voyage AI Client
            api_key = os.getenv("VOYAGE_API_KEY")
            if not api_key:
                logger.warning("⚠️ VOYAGE_API_KEY not found. Vector embedding will fail.")
            else:
                self._client = voyageai.Client(api_key=api_key)
                
            # 2. Cross-Encoder (Reranking) - Keep local for speed/cost?
            # Or use Voyage reranker? User asked to replace LaBSE algorithm.
            # Local reranker is fine to keep for now unless specified.
            # It's small.
            device = "cpu"
            self._cross_encoder = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', device=device)
            
            logger.info("✅ Retrieval Models Loaded (Voyage AI + CrossEncoder).")
        except Exception as e:
            logger.error(f"❌ Error loading models: {e}", exc_info=True)

    def clean_tags(self, text: str) -> str:
        """Strips XML-like tags for embedding."""
        if not text: return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\[(TAB|COMMENT|SHAPE)\]', '', text)
        return text.strip()

    def embed_batch(self, texts: List[str], input_type: str = "document") -> List[List[float]]:
        """
        Wraps Voyage AI embedding call.
        """
        if not self._client or not texts:
            return []
            
        try:
            # Voyage 3.5 is the current recommendation (2048 or 1024 dim).
            # User requested 2048 explicitly in prompt.
            # "upgrade our vector to 2048"
            # model="voyage-3-large" or "voyage-3.5" (supports 2048)
            # Default for 3.5 is 1024. Need to specify output_dimension=2048?
            # Docs say: voyage-3.5 supports 2048.
            
            # Filter empty strings to avoid API error
            valid_texts = [t for t in texts if t.strip()]
            if not valid_texts: return []
            
            # Map back indices if we filtered blanks? 
            # Ideally we send blanks as something or just handle mismatch.
            # Simpler: replace blank with " "
            sanitized = [t if t.strip() else " " for t in texts]

            result = self._client.embed(
                sanitized, 
                model="voyage-3-large", 
                input_type=input_type,
                output_dimension=2048
            )
            return result.embeddings
            
        except Exception as e:
            logger.error(f"Voyage AI Embedding Error: {e}")
            return []

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
        
        # 2. Vector Search
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
        if not self._client: return []
        
        query_vec = None
        
        # Try to use pre-calculated Segment Vector
        if segment_id:
            seg = db.query(Segment).filter(Segment.id == segment_id).first()
            if seg and seg.embedding is not None:
                query_vec = seg.embedding
                # logger.info(f"Using pre-calculated vector for segment {segment_id}")

        # Fallback to Inference
        if query_vec is None:
            clean_query = self.clean_tags(query)
            try:
                # Use query input_type
                b = self.embed_batch([clean_query], input_type="query")
                if b: query_vec = b[0]
            except:
                return []
        
        if not query_vec: return []
            
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
            matches.append(TranslationMatch(
                id=chunk.id,
                content=chunk.rich_content or chunk.content,
                source_text=chunk.content, # The source chunk
                filename=file.filename,
                type="context", 
                category=file.category,
                score=0, # Placeholder, updated by reranker
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
            logit = float(scores[i])
            match.raw_logit = logit
            
            import math
            prob = 1 / (1 + math.exp(-logit))
            match.score = int(prob * 100)
            
            if match.category != ProjectFileCategory.legal:
                match.score = max(0, match.score - 5)
                
        return [m for m in candidates if m.score > 40]
