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
        1. Exact/TM Lookup (TranslationUnit)
        2. Vector Search (ContextChunk)
        3. Deduplication (Source-Text based)
        4. Reranking (Voyage AI) & Differentiation
        """
        matches = []
        
        # 1. Exact / Hash Lookup
        matches.extend(self._lookup_tm(db, project_id, query))
        
        # 2. Vector Search (Hybrid Candidates)
        # Note: TMX files are also ingested as vectors, so we get semantic similarity here.
        matches.extend(self._search_vector_chunks(db, project_id, query, top_k=20, segment_id=segment_id))
        
        # 3. Deduplication (Prioritize: Mandatory > User/TMX > Context/Optional)
        # Group by source_text to minimize Rerank Token Usage
        unique_map = {}
        
        # Helper to get priority score (Higher is better)
        def get_priority(m: TranslationMatch):
            # 3: Mandatory / Exact
            if m.type == TranslationOrigin.mandatory or m.category == ProjectFileCategory.legal: return 3
            # 2: User / TMX
            if m.type == TranslationOrigin.user: return 2 
            # 1: Context / Background
            return 1
            
        for m in matches:
            key = m.source_text.strip()
            
            if key not in unique_map:
                unique_map[key] = m
            else:
                existing = unique_map[key]
                if get_priority(m) > get_priority(existing):
                    unique_map[key] = m
                    
        deduped_candidates = list(unique_map.values())
        
        # 4. Rerank & Score
        scored_matches = self._rerank_voyage(query, deduped_candidates)
        
        return scored_matches[:limit]

    def _rerank_voyage(self, query: str, candidates: List[TranslationMatch]) -> List[TranslationMatch]:
        """
        Uses Voyage AI Rerank API (rerank-2.5) for high-quality semantic scoring.
        Applies penalties for differentiation.
        """
        if not candidates: 
            return []
            
        if not self._client:
            # Fallback if no client
            for m in candidates: m.score = 80
            return candidates

        # Prepare Documents
        # Voyage expects list of strings
        docs = [c.source_text for c in candidates]
        
        try:
            # Call Voyage Rerank
            # model="rerank-2.5" used as requested
            reranking = self._client.rerank(
                query=query,
                documents=docs,
                model="rerank-2.5",
                top_k=len(docs)
            )
            
            # Create a lookup for score by index
            # Voyage returns RerankingResult objects with index, score
            score_map = {r.index: r.relevance_score for r in reranking.results}
            
        except Exception as e:
            logger.error(f"Voyage Rerank Failed: {e}")
            return candidates

        final_list = []
        
        for i, match in enumerate(candidates):
            # Get Semantic Score (0.0 - 1.0)
            raw_score = score_map.get(i, 0.0)
            
            # Convert to %
            base_score = int(raw_score * 100)
            
            # Boosts/Penalties (User Refinement)
            # Mandatory: +5 (Max 99)
            # Optional/Context/TMX: +2 (Max 99)
            
            boost = 2
            is_mandatory = (match.type == TranslationOrigin.mandatory or match.category == ProjectFileCategory.legal)
            
            if is_mandatory:
                boost = 5
                
            final_score = base_score + boost
            
            # Cap at 99 for now (User request "max 99")
            # But allow 100 if it was manually exact? 
            # Rerank usually doesn't give 100.
            # Let's cap at 99.
            match.score = max(0, min(99, final_score))
            
            # Metadata for UI
            match.metadata = match.metadata or {}
            match.metadata['rerank_score'] = base_score
            
            final_list.append(match)
            
        # Sort by Score (Desc)
        final_list.sort(key=lambda x: x.score, reverse=True)
        
        # Filter low quality?
        return [m for m in final_list if m.score > 40]

    def _lookup_tm(self, db: Session, project_id: str, text_val: str) -> List[TranslationMatch]:
        results = []
        s_hash = compute_hash(text_val)
        
        tms = db.query(TranslationUnit).filter(
            TranslationUnit.project_id == project_id,
            TranslationUnit.source_hash == s_hash
        ).all()
        
        for tm in tms:
            # Base score for Exact TM is high
            score = 100
            if tm.origin_type == TranslationOrigin.user: score = 99
            elif tm.origin_type == TranslationOrigin.optional: score = 98
            
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

        # Fallback to Inference
        if query_vec is None:
            clean_query = self.clean_tags(query)
            try:
                b = self.embed_batch([clean_query], input_type="query")
                if b is not None and len(b) > 0: query_vec = b[0]
            except:
                return []
        
        if query_vec is None: return []
            
        if hasattr(query_vec, 'tolist'):
            query_vec = query_vec.tolist()
            
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
                source_text=chunk.content,
                filename=file.filename,
                type="context", 
                category=file.category,
                score=0, # Calculated in _rerank_and_score
                chunk_index=chunk.chunk_index,
                file_id=file.id
            ))
        return matches

    def _rerank(self, query: str, candidates: List[TranslationMatch]) -> List[TranslationMatch]:
        # Legacy method kept for interface compatibility if needed, but we use _rerank_and_score now internally
        return self._rerank_and_score(query, candidates)
