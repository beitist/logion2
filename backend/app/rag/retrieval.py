import logging
import difflib
import re
import os
import voyageai
from rapidfuzz import fuzz
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
            model_name = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
            try:
                # Try offline first (avoids HuggingFace HEAD request timeouts)
                self._cross_encoder = CrossEncoder(model_name, device=device, local_files_only=True)
            except Exception:
                # First run: download from HuggingFace
                self._cross_encoder = CrossEncoder(model_name, device=device)
            
            logger.info("✅ Retrieval Models Loaded (Voyage AI + CrossEncoder).")
        except Exception as e:
            logger.error(f"❌ Error loading models: {e}", exc_info=True)

    def clean_tags(self, text: str) -> str:
        """Strips XML-like tags for embedding."""
        if not text: return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\[(TAB|COMMENT|SHAPE)\]', '', text)
        return text.strip()

    def embed_batch(self, texts: List[str], input_type: str = "document") -> tuple[List[List[float]], int]:
        """
        Wraps Voyage AI embedding call.
        Returns: (embeddings, total_tokens)
        """
        if not self._client or not texts:
            return [], 0
            
        try:
            # Filter empty strings
            valid_texts = [t for t in texts if t.strip()]
            if not valid_texts: return [], 0
            
            sanitized = [t if t.strip() else " " for t in texts]

            result = self._client.embed(
                sanitized, 
                model="voyage-3-large", 
                input_type=input_type,
                output_dimension=2048
            )
            return result.embeddings, result.total_tokens
            
        except Exception as e:
            logger.error(f"Voyage AI Embedding Error: {e}")
            return [], 0

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
        total_embedding_tokens = 0
        total_rerank_tokens = 0
        
        # 1. Exact / Hash Lookup
        matches.extend(self._lookup_tm(db, project_id, query))
        
        # 2. Vector Search (Hybrid Candidates)
        # Note: TMX files are also ingested as vectors, so we get semantic similarity here.
        vector_matches, embedding_tokens = self._search_vector_chunks(db, project_id, query, top_k=20, segment_id=segment_id)
        matches.extend(vector_matches)
        total_embedding_tokens += embedding_tokens
        
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
            key = self.clean_tags(m.source_text).strip()

            if key not in unique_map:
                unique_map[key] = m
            else:
                existing = unique_map[key]
                if get_priority(m) > get_priority(existing):
                    unique_map[key] = m
                    
        deduped_candidates = list(unique_map.values())
        
        # 4. Rerank & Score
        scored_matches, rerank_tokens = self._rerank_voyage(query, deduped_candidates)
        total_rerank_tokens += rerank_tokens

        logger.info(f"Retrieval Usage: Embedding Tokens={total_embedding_tokens}, Rerank Tokens={total_rerank_tokens}")
        
        usage_dict = {
            "voyage-3-large": total_embedding_tokens,
            "rerank-2.5": total_rerank_tokens
        }
        
        return scored_matches[:limit], usage_dict

    def _rerank_voyage(self, query: str, candidates: List[TranslationMatch]) -> tuple[List[TranslationMatch], int]:
        """
        Uses Voyage AI Rerank API (rerank-2.5).
        Returns (matches, token_usage)
        """
        if not candidates: 
            return [], 0
            
        if not self._client:
            for m in candidates: m.score = 80
            return candidates, 0

        # Prepare Documents — strip XML tags so they don't affect relevance scoring
        clean_query = self.clean_tags(query)
        docs = [self.clean_tags(c.source_text) for c in candidates]

        # Instruction prefix: guide rerank-2.5 to score translation equivalence,
        # not generic topical relevance
        instructed_query = (
            "Find segments that are direct translations, paraphrases, or close "
            "semantic equivalents of the following source text. "
            "Prefer segment-level matches over longer paragraphs.\n\n"
            + clean_query
        )

        try:
            reranking = self._client.rerank(
                query=instructed_query,
                documents=docs,
                model="rerank-2.5",
                top_k=len(docs)
            )
            
            score_map = {r.index: r.relevance_score for r in reranking.results}
            tokens = reranking.total_tokens
            
        except Exception as e:
            logger.error(f"Voyage Rerank Failed: {e}")
            return candidates, 0

        final_list = []
        query_chars = len(clean_query)

        for i, match in enumerate(candidates):
            raw_score = score_map.get(i, 0.0)

            # Length penalty: only penalize candidates much LONGER than query (>3x)
            # A paragraph matching on a single keyword should not outscore a segment-level match
            doc_chars = len(docs[i])
            if query_chars > 0 and doc_chars > query_chars * 3:
                length_factor = (query_chars * 3) / doc_chars  # 5x→0.6, 10x→0.3
            else:
                length_factor = 1.0

            adjusted_score = raw_score * length_factor
            base_score = int(adjusted_score * 100)

            # Boosts/Penalties
            boost = 2
            is_mandatory = (match.type == TranslationOrigin.mandatory or match.category == ProjectFileCategory.legal)

            if is_mandatory:
                boost = 5

            final_score = base_score + boost
            match.score = max(0, min(99, final_score))
            
            match.metadata = match.metadata or {}
            match.metadata['rerank_score'] = base_score
            
            final_list.append(match)
            
        final_list.sort(key=lambda x: x.score, reverse=True)
        return [m for m in final_list if m.score > 35], tokens

    def _lookup_tm(self, db: Session, project_id: str, text_val: str) -> List[TranslationMatch]:
        """
        Exact Match / Hash Lookup from TranslationUnit table.
        """
        import hashlib
        query_norm = text_val.strip()
        query_hash = hashlib.sha256(query_norm.encode('utf-8')).hexdigest()
        
        # Exact Hash Lookup
        units = db.query(TranslationUnit).filter(
            TranslationUnit.project_id == project_id,
            TranslationUnit.source_hash == query_hash
        ).all()
        
        results = []
        for tm in units:
            # Base score for Exact TM is high
            score = 100
            if tm.origin_type == TranslationOrigin.user: score = 99
            elif tm.origin_type == TranslationOrigin.optional: score = 98
            
            if not tm.target_text:
                continue
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

    def _search_vector_chunks(self, db: Session, project_id: str, query: str, top_k: int = 30, segment_id: str = None) -> tuple[List[TranslationMatch], int]:
        if not self._client: return [], 0
        
        query_vec = None
        current_tokens = 0
        
        # Try to use pre-calculated Segment Vector
        if segment_id:
            seg = db.query(Segment).filter(Segment.id == segment_id).first()
            if seg and seg.embedding is not None:
                query_vec = seg.embedding

        # Fallback to Inference
        if query_vec is None:
            clean_query = self.clean_tags(query)
            try:
                # Expecting (embeddings, tokens)
                embeddings, tokens = self.embed_batch([clean_query], input_type="query")
                if embeddings and len(embeddings) > 0: 
                    query_vec = embeddings[0]
                    current_tokens = tokens
            except:
                return [], 0
        
        if query_vec is None: return [], 0
            
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
                type=TranslationOrigin.mandatory if file.category == ProjectFileCategory.legal else TranslationOrigin.optional,
                category=file.category,
                score=0, # Calculated in _rerank_and_score
                chunk_index=chunk.chunk_index,
                file_id=file.id
            ))

        # Log how many context chunks were found and from which categories.
        # This helps diagnose why mandatory/optional matches may not appear in the UI.
        if matches:
            cats = {}
            for m in matches:
                cats[m.category] = cats.get(m.category, 0) + 1
            logger.info(f"Vector search: {len(matches)} chunks found for project {project_id} — by category: {cats}")
        else:
            logger.warning(f"Vector search: 0 chunks found for project {project_id}. "
                           f"Check if legal/background files have been ingested (ContextChunk table).")

        return matches, current_tokens

    def search_internal_tm(self, db: Session, project_id: str, segment_id: str,
                           limit: int = 3, min_score: int = 50) -> List[TranslationMatch]:
        """
        Search for similar already-translated segments in the same project.
        1. Fuzzy text match (rapidfuzz) for near-identical segments
        2. Cosine pre-filter via pgvector to get candidates
        3. Voyage AI rerank for accurate scoring
        4. Merge, deduplicate, filter by min_score
        """
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        if not segment:
            return []

        # --- Stage 1: Fuzzy text match (cheap, no API calls) ---
        # Fuzzy threshold: use min_score but floor at 80 (rapidfuzz scores are generous)
        fuzzy_threshold = max(min_score, 80)
        fuzzy_matches = self._fuzzy_internal_tm(db, project_id, segment, fuzzy_threshold)
        seen_ids = {m.id for m in fuzzy_matches}

        # --- Stage 2: Vector-based candidates (requires embedding) ---
        vector_candidates = []
        if segment.embedding is not None:
            query_vec = segment.embedding
            if hasattr(query_vec, 'tolist'):
                query_vec = query_vec.tolist()

            dist_col = Segment.embedding.cosine_distance(query_vec).label("dist")
            results = db.query(Segment, dist_col).filter(
                Segment.project_id == project_id,
                Segment.id != segment_id,
                Segment.target_content.isnot(None),
                Segment.target_content != "",
                Segment.status.in_(["translated", "mt_draft"]),
                Segment.embedding.isnot(None),
            ).order_by("dist").limit(20).all()

            for r, dist in results:
                if dist > 0.5:
                    break
                match_id = f"internal-{r.id}"
                if r.source_content == segment.source_content or match_id in seen_ids:
                    continue
                vector_candidates.append(TranslationMatch(
                    id=match_id,
                    content=r.target_content,
                    source_text=r.source_content,
                    type="internal",
                    category="tm",
                    score=0,
                    filename="Project TM",
                ))

            if vector_candidates:
                scored, _ = self._rerank_internal_tm(segment.source_content, vector_candidates)
                vector_candidates = [m for m in scored if m.score >= min_score]

        # --- Stage 3: Merge and return ---
        combined = fuzzy_matches + vector_candidates
        combined.sort(key=lambda x: x.score, reverse=True)
        return combined[:limit]

    def _fuzzy_internal_tm(self, db: Session, project_id: str, segment: Segment, min_ratio: int = 85) -> List[TranslationMatch]:
        """Fast fuzzy match on tag-stripped source text using rapidfuzz."""
        clean_query = self.clean_tags(segment.source_content or "")
        if not clean_query or len(clean_query) < 5:
            return []

        # Fetch translated segments (no embedding required)
        candidates = db.query(Segment).filter(
            Segment.project_id == project_id,
            Segment.id != segment.id,
            Segment.target_content.isnot(None),
            Segment.target_content != "",
            Segment.status.in_(["translated", "mt_draft"]),
        ).all()

        matches = []
        for c in candidates:
            if c.source_content == segment.source_content:
                continue  # Skip exact repetitions
            clean_candidate = self.clean_tags(c.source_content or "")
            if not clean_candidate:
                continue
            ratio = fuzz.ratio(clean_query, clean_candidate)
            if ratio >= min_ratio:
                matches.append(TranslationMatch(
                    id=f"internal-{c.id}",
                    content=c.target_content,
                    source_text=c.source_content,
                    type="internal",
                    category="tm",
                    score=int(ratio),
                    filename="Project TM",
                ))

        matches.sort(key=lambda x: x.score, reverse=True)
        return matches[:5]  # Cap before merge

    def _rerank_internal_tm(self, query: str, candidates: List[TranslationMatch]) -> tuple[List[TranslationMatch], int]:
        """Rerank internal TM candidates using Voyage AI rerank-2.5."""
        if not candidates:
            return [], 0

        if not self._client:
            # Fallback: rough cosine-based score
            for m in candidates:
                m.score = 60
            return candidates, 0

        clean_query = self.clean_tags(query)
        docs = [self.clean_tags(c.source_text) for c in candidates]

        try:
            reranking = self._client.rerank(
                query=clean_query,
                documents=docs,
                model="rerank-2.5",
                top_k=len(docs)
            )

            for r in reranking.results:
                candidates[r.index].score = int(r.relevance_score * 100)

            candidates.sort(key=lambda x: x.score, reverse=True)
            return candidates, reranking.total_tokens

        except Exception as e:
            logger.error(f"Internal TM Rerank Failed: {e}")
            return candidates, 0

    def _rerank(self, query: str, candidates: List[TranslationMatch]) -> List[TranslationMatch]:
        # Legacy method kept for interface compatibility if needed, but we use _rerank_and_score now internally
        return self._rerank_and_score(query, candidates)
