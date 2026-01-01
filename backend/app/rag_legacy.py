from .tmx import compute_hash, normalize_text
import logging
from .logger import get_logger
from .models import TranslationUnit, TranslationOrigin

logger = get_logger("RAG")
import os
import math
import google.generativeai as genai
from sqlalchemy.orm import Session
from .models import Project, ProjectFile, ContextChunk, ProjectFileCategory
from .storage import download_file
from dotenv import load_dotenv
import zipfile
import re
from datetime import datetime
import asyncio
from xml.etree import ElementTree
import torch
import pysbd
from sentence_transformers import SentenceTransformer, CrossEncoder, util
import numpy as np

# Use shared parser
from .document.parser import parse_document
from .config import get_default_model_id

load_dotenv()

# Configure Gemini (Still used for generative tasks)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- LOAD LOCAL MODELS ---
# We load them once at startup.
# Check for MPS (Apple Silicon)
# device = "mps" if torch.backends.mps.is_available() else "cpu"
device = "cpu" # Force CPU due to MPS stability issues (SIGABRT in HeapAllocator)
logger.info(f"Loading Models on {device}...")

try:
    # 1. Bi-Encoder (LaBSE) - 768 Dimensions
    # Using 'sentence-transformers/LaBSE'
    _bi_encoder = SentenceTransformer('sentence-transformers/LaBSE', device=device)
    
    # 2. Cross-Encoder (Reranking)
    # Using 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
    _cross_encoder = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', device=device)
    
    logger.info("✅ Models Loaded Successfully.")
    
    # 3. Semantic Aligner (SpaCy + Vectors)
    from .aligner import SemanticAligner
    _aligner = SemanticAligner(_bi_encoder)
    
except Exception as e:
    logger.error(f"❌ Error loading models: {e}", exc_info=True)
    _bi_encoder = None
    _cross_encoder = None
    _aligner = None
    
def clean_tags(text: str) -> str:
    """Strips XML-like tags (<1>, </1>) and [TAB]/[COMMENT] markers for embedding."""
    if not text: return ""
    # Strip <...>
    # We want to remove <1>, <b pt="..."/>, etc.
    text = re.sub(r'<[^>]+>', '', text)
    # Strip [TAB], [COMMENT] checks
    text = re.sub(r'\[(TAB|COMMENT|SHAPE)\]', '', text)
    return text.strip()




# --- Ingestion ---

from .database import SessionLocal
from .glossary_service import GlossaryMatcher

def reingest_project(project_id: str):
    """
    Clears existing RAG vectors and re-runs ingestion.
    """
    db = SessionLocal()
    try:
        # 1. Clear existing chunks
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return
            
        # Delete chunks for this project's files
        file_ids = db.query(ProjectFile.id).filter(ProjectFile.project_id == project_id).all()
        file_ids = [f[0] for f in file_ids]
        
        if file_ids:
            db.query(ContextChunk).filter(ContextChunk.file_id.in_(file_ids)).delete(synchronize_session=False)
            db.commit()
            
        # 2. Reset log
        project.ingestion_logs = []
        project.rag_status = "created"
        db.commit()
        db.close()
        
        # 3. Call Ingest
        ingest_project_files(project_id)
        
    except Exception as e:
        print(f"Re-Ingest Error: {e}")

def ingest_project_files(project_id: str):
    """
    Task to be run in background.
    """
    db = SessionLocal()
    
    def log_msg(msg: str):
        logger.info(msg) # Unified File Logging
        try:
             p = db.query(Project).filter(Project.id == project_id).first()
             current_logs = list(p.ingestion_logs) if p.ingestion_logs else []
             from datetime import datetime
             current_logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
             p.ingestion_logs = current_logs
             db.commit()
        except Exception as e:
             logger.error(f"Log error: {e}")

    try:
        if not _bi_encoder:
            log_msg("FATAL: Encoder models not loaded.")
            return

        log_msg(f"Starting Cross-Lingual Ingestion for project {project_id}")
        
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return

        project.rag_status = "ingesting"
        db.commit()
    
        # Categories to ingest (excluding Source)
        categories_to_ingest = [
            ProjectFileCategory.legal.value, 
            ProjectFileCategory.background.value
        ]
        
        target_files = db.query(ProjectFile).filter(
            ProjectFile.project_id == project_id,
            ProjectFile.category.in_(categories_to_ingest)
        ).all()
        
        log_msg(f"Found {len(target_files)} files to process (Legal/Background).")

        total_chunks = 0
        BATCH_SIZE = 32
        
        for file_record in target_files:
            log_msg(f"Processing file: {file_record.filename} ({file_record.category})...")
            
            temp_path = f"temp_rag_{file_record.id}_{file_record.filename}"
            try:
                download_file(file_record.file_path, temp_path)
                
                # CHECK FOR TMX
                if file_record.filename.lower().endswith('.tmx'):
                    log_msg(f"Detected TMX file: {file_record.filename}")
                    
                    if not _aligner:
                         log_msg("WARNING: Aligner not loaded. Using fallback direct ingestion.")
                         origin = TranslationOrigin.mandatory if file_record.category == "legal" else TranslationOrigin.optional
                         from .tmx import ingest_tmx_direct
                         ingest_tmx_direct(temp_path, project_id, origin, db)
                         continue
                        
                    log_msg("Aligning TMX segments with SpaCy...")
                    from .tmx import parse_tmx_units, compute_hash
                    
                    origin_type = TranslationOrigin.mandatory if file_record.category == "legal" else TranslationOrigin.optional
                    
                    tm_buffer = []
                    chunk_buffer = []
                    aligned_count = 0
                    
                    for unit in parse_tmx_units(temp_path):
                        # unit = {source_text, target_text} (Target is XML-tagged)
                        # Aligner expects plain text generally, but our aligner preserves tags via protect_tags!
                        # So we pass the tagged XML to aligner.
                        
                        pairs = _aligner.align(unit['source_text'], unit['target_text'])
                        
                        for p in pairs:
                             # p = {source, target, score, type}
                             # 1. Translation Unit (Exact Match)
                             s_hash = compute_hash(p['source'])
                             tm_buffer.append({
                                "project_id": project_id,
                                "source_hash": s_hash,
                                "source_text": p['source'],
                                "target_text": p['target'],
                                "origin_type": origin_type.value,
                                "created_at": datetime.utcnow(),
                                "changed_at": datetime.utcnow()
                             })
                             
                             # 2. Context Chunk (Vector)
                             # Embed source for search
                             # Note: Aligner already computed vectors but we can't easily retrieve them here 
                             # without refactoring aligner to return them.
                             # For now, we re-embed or modify aligner. 
                             # Optimization: Let's accept re-embedding for now (simpler).
                             # Or better: `_bi_encoder.encode` is fast.
                             
                             # Store pair in Chunk
                             chunk_buffer.append({
                                 "text": p['source'],
                                 "rich": p['target'],
                                 "src_seg": p['source'],
                                 "tgt_seg": p['target'],
                                 "score": p['score'],
                                 "type": p['type']
                             })
                             aligned_count += 1
                    
                    # Flush TM
                    if tm_buffer:
                         from .tmx import _flush_buffer
                         _flush_buffer(tm_buffer, db)
                    
                    # Flush and Embed Chunks
                    log_msg(f"Aligned {aligned_count} segments. Generating vectors...")
                    
                    for i in range(0, len(chunk_buffer), BATCH_SIZE):
                        batch = chunk_buffer[i : i + BATCH_SIZE]
                        
                        # Optimization: Remove tags for embedding to ensure best semantic match
                        # We still store the tagged version in rich_content (and content)
                        
                        embed_texts = [clean_tags(b['text']) for b in batch]
                        embeddings = _bi_encoder.encode(embed_texts, convert_to_numpy=True, normalize_embeddings=True)
                        
                        db_chunks = []
                        for b, vec in zip(batch, embeddings):
                            # 1. Source-based Chunk (Standard) - Search Source, Display Target
                            db_chunks.append(ContextChunk(
                                file_id=file_record.id,
                                content=b['text'], # Source
                                rich_content=b['rich'], # Target with tags
                                embedding=vec.tolist(),
                                source_segment=b['src_seg'],
                                target_segment=b['tgt_seg'],
                                alignment_score=b['score'],
                                alignment_type=b['type']
                            ))
                            
                            # 2. Target-based Chunk (Augmentation) - Search Target, Display Target
                            # Allows finding the segment even if Source is bad/mismatched but Target matches Query (Cross-Lingual)
                            # We need to compute embedding for Target.
                            # Optimization: Do we compute it here or add to batch?
                            # Adding to this loop is hard because vectors are already computed.
                            # We can just rely on Source search for now? 
                            # NO, looking at the logs, Source search failed (0.62). Target search would execute 0.88.
                            # So strictly we MUST index target.
                            pass
                            
                        db.add_all(db_chunks)
                        db.commit()
                        
                        # Compute Target Augmentation properly
                        # Create a secondary batch for targets
                        tgt_texts = [clean_tags(b['rich']) for b in batch]
                        tgt_vecs = _bi_encoder.encode(tgt_texts, convert_to_numpy=True, normalize_embeddings=True)
                        
                        tgt_chunks = []
                        for b, t_vec in zip(batch, tgt_vecs):
                             tgt_chunks.append(ContextChunk(
                                file_id=file_record.id,
                                content=b['rich'], # Target (Cleaned? No, DB content usually raw. We used clean for embedding)
                                # Actually, storing Tagged Target in 'content' is fine.
                                rich_content=b['rich'], # Display Target
                                embedding=t_vec.tolist(),
                                source_segment=b['src_seg'], # Meta info remains same
                                target_segment=b['tgt_seg'],
                                alignment_score=b['score'],
                                alignment_type=b['type']
                            ))
                        db.add_all(tgt_chunks)
                        db.commit()

                        total_chunks += len(batch)
                        
                    continue
                
                # Unified Ingestion via Parser
                if file_record.filename.endswith(".docx"):
                    # Define custom segmentation wrapper
                    def custom_segmentation(text):
                        if _aligner:
                            # Language detection simple
                            de_markers = ['der ', 'die ', 'das ', 'und ', ' ist ', ' mit ', ' für ', 'e.V.']
                            score_de = sum(1 for m in de_markers if m in text.lower())
                            lang = "de" if score_de >= 1 else "en"
                            return _aligner.segment_text(text, lang=lang)
                        else:
                            # Fallback if aligner failed
                             return [text]

                    log_msg("Parsing DOCX with shared parser...")
                    segments = parse_document(temp_path, segmentation_func=custom_segmentation)
                    
                    # Extract chunks from segments
                    chunks = []
                    for seg in segments:
                        txt = seg.source_text.strip()
                        if txt and len(txt) > 3:
                            chunks.append(txt)
                            
                    log_msg(f"Generated {len(chunks)} semantic segments (Parser). Encoding...")
                    
                    # 4. Embed & Store
                    for i in range(0, len(chunks), BATCH_SIZE):
                        batch = chunks[i : i + BATCH_SIZE]
                        
                        # LaBSE Encoding
                        embed_texts = [clean_tags(t) for t in batch]
                        embeddings = _bi_encoder.encode(embed_texts, convert_to_numpy=True, normalize_embeddings=True)
                        
                        db_chunks = []
                        for content, vector in zip(batch, embeddings):
                            db_chunks.append(ContextChunk(
                                file_id=file_record.id,
                                content=content, 
                                embedding=vector.tolist()
                            ))
                        
                        db.add_all(db_chunks)
                        db.commit() 
                        total_chunks += len(batch)
                        log_msg(f"Stored batch {i // BATCH_SIZE + 1}.")
                
                else: 
                     log_msg(f"Skipping {file_record.filename} (unsupported format)")
                     continue
                        
            except Exception as e:
                log_msg(f"ERROR processing {file_record.filename}: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)


        project.rag_status = "ready"
        log_msg(f"RAG READY. Knowledge base refreshed: {total_chunks} alignment vectors.")
        
        # Trigger Auto-Draft (DISABLED for safety/cost)
        # log_msg("Starting automatic draft generation...")
        # generate_project_drafts(project_id)
        
        db.commit()

    except Exception as e:
        log_msg(f"FATAL ERROR: {e}")
        try:
             project.rag_status = "error"
             db.commit()
        except:
             pass
    finally:
        db.close()

# --- Search Logic ---

import difflib

def calculate_hybrid_score(query: str, candidate: str):
    """
    Computes a hybrid similarity score (0-100) and details.
    Strategies:
    1. Levenshtein Ratio (Char based)
    2. Token Jaccard (Word based) - handles reordering/stemming proxies
    """
    if not query or not candidate: return 0, ""
    
    q_norm = normalize_text(query).lower()
    c_norm = normalize_text(candidate).lower()
    
    # 1. Levenshtein
    lev_ratio = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
    lev_score = int(lev_ratio * 100)
    
    # 2. Token Jaccard
    # Simple tokenization
    q_tokens = set(q_norm.split())
    c_tokens = set(c_norm.split())
    
    if not q_tokens or not c_tokens:
        tok_score = 0
    else:
        intersection = len(q_tokens & c_tokens)
        union = len(q_tokens | c_tokens)
        tok_score = int((intersection / union) * 100)
        
    # 3. Hybrid Max
    final_score = max(lev_score, tok_score)
    
    details = f"Lev:{lev_score}, Tok:{tok_score}"
    return final_score, details

def extract_numbers(text):
    # Remove tags <1>, </1>, <1 /> before extracting numbers
    # otherwise segment ID tags count as 'missing numbers' if the match doesn't have them.
    text_no_tags = re.sub(r'</?\d+( /)?>', '', text)
    return set(re.findall(r'\d+', text_no_tags))

def search_context_for_segment(segment_text: str, project_id: str, db: Session, limit=30, threshold=0.0):
    """
    Retrieves chunks using Hybrid Search (Hash Exact Match + LaBSE Vector).
    """
    if not segment_text or len(segment_text) < 2:
        return []

    # 0. Classic TMX Lookup (Exact Match) - The "Professional" Part
    exact_matches = []
    try:
        s_hash = compute_hash(segment_text)
        tm_results = db.query(TranslationUnit).filter(
            TranslationUnit.project_id == project_id, # Scoped to project for now (Project TM)
            TranslationUnit.source_hash == s_hash
        ).all()
        
        # Sort Priority: Mandatory > User > Optional
        def priority_key(tm):
            if tm.origin_type == "mandatory": return 3
            if tm.origin_type == "user": return 2
            return 1
            
        tm_results.sort(key=priority_key, reverse=True)
        
        for tm in tm_results:
            exact_matches.append({
                "id": f"tm-{tm.id}",
                "content": tm.target_text,
                "filename": "Translation Memory", 
                "type": tm.origin_type, # 'mandatory', 'user', 'optional'
                "category": "tm",
                "score": 100
            })
    except Exception as e:
        logger.error(f"TM Lookup Error for '{segment_text[:20]}...': {e}", exc_info=True)

    # 0.5 Fuzzy (Hybrid) Match - The "Almost Exact" Part
    # User requested tolerance for ~75% match (3/4 words)
    # Combining Trigram Distance (<->) AND FTS (@@)
    try:
        from sqlalchemy import text
        
        # We query for candidates that are EITHER:
        # 1. Trigram close (< 0.4 distance = > 60% char similarity) to catch typos in long words
        # 2. FTS Match (Stemming) to catch "sources" vs "source"
        
        # Note: FTS 'plainto_tsquery' converts "Information sources" -> "inform & sourc"
        
        sql = text("""
            SELECT id, source_text, target_text, origin_type
            FROM translation_units
            WHERE project_id = :pid 
              AND (
                  (source_text <-> :query) < 0.45 
                  OR 
                  (to_tsvector('english', source_text) @@ plainto_tsquery('english', :query))
              )
            LIMIT 10;
        """)
        
        # We fetch up to 10 candidates to re-score in Python
        fuzzy_results = db.execute(sql, {"query": segment_text, "pid": project_id}).fetchall()
        
        hybrid_candidates = []
        
        for row in fuzzy_results:
            # row: (id, source, target, origin)
            cand_src = row[1]
            
            # Python Re-Scoring
            score, details = calculate_hybrid_score(segment_text, cand_src)
            
            # Apply Threshold (e.g. 60%) to filter out FTS noise
            if score < 60: continue
            
            hybrid_candidates.append({
                "id": f"tm-{row[0]}",
                "content": row[2], # Target
                "filename": f"TM (Hybrid {details})", 
                "type": row[3], 
                "category": "tm",
                "score": score
            })
            
        # Sort by score desc
        hybrid_candidates.sort(key=lambda x: x['score'], reverse=True)
        
        # Add top 5 unique
        for cand in hybrid_candidates[:5]:
            if not any(em['id'] == cand['id'] for em in exact_matches):
                exact_matches.append(cand)
            
    except Exception as e:
        # Fallback
        pass # print(f"Fuzzy lookup error: {e}")

    if not _bi_encoder:
        return exact_matches

    # 1. Bi-Encoder Retrieval (Recall)
    try:
        # Encode Query (Source English)
        query_vector = _bi_encoder.encode(clean_tags(segment_text), normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"Embedding error: {e}")
        return []
    
    # Search for Top K (30) candidates
    results = db.query(ContextChunk, ProjectFile)\
        .join(ProjectFile)\
        .filter(ProjectFile.project_id == project_id)\
        .order_by(ContextChunk.embedding.cosine_distance(query_vector))\
        .limit(limit)\
        .all()
        
    if not results:
        return []

    # 2. Reranking (Precision)
    # Prepare pairs: [Query, German Candidate]
    candidates = [r[0].content for r in results]
    pairs = [[segment_text, doc] for doc in candidates]
    
    try:
        # Get Cross-Encoder Logits
        scores = _cross_encoder.predict(pairs)
    except Exception as e:
        logger.error(f"Reranking error: {e}", exc_info=True)
        import numpy as np
        scores = np.zeros(len(candidates)) # Fallback
    
    # 3. Heuristics & Number Penalty
    final_matches = []
    
    query_numbers = extract_numbers(segment_text)
    
    for idx, (chunk, file) in enumerate(results):
        base_score = float(scores[idx]) # Logit score (approx -10 to 10)
        
        # --- Refactored Scoring Logic (2025-12-16) ---
        from .scoring import ScoringEngine

        # Determine strictness model for Linguistic Checks (if needed)
        # We try to use the correct SpaCy model if available
        nlp = None
        if _aligner:
            # Simple heuristic for lang detection
            is_german = any(w in segment_text.lower().split() for w in ['die', 'der', 'das', 'dem', 'den', 'und', 'mit', 'auf'])
            nlp = _aligner.nlp_de if is_german else _aligner.nlp_en

        # Calculate Logic
        # We pass the Raw Logit (base_score). The engine applies ALL penalties (Number, Length, POS).
        ui_score, applied_penalties = ScoringEngine.calculate_score(segment_text, chunk.content, base_score, nlp)
        
        # If score is too low, filter it out
        if ui_score < 30: # Implicit filtering
             continue

        match_type = "mandatory" if file.category == "legal" else "optional"
        
        # Penalty for Optional Matches (-1%)
        if match_type != "mandatory":
            ui_score = max(0, ui_score - 1)
        
        # Use Rich Content (with Tags) if available, else plain content
        display_content = chunk.rich_content if chunk.rich_content else chunk.content
        
        final_matches.append({
            "id": chunk.id,
            "content": display_content,
            "filename": file.filename,
            "type": match_type,
            "category": file.category,
            "score": int(ui_score), # Integer format
            "raw_logit": base_score # Helper for debugging, unpenalized
        })

    # Sort by Final UI Score
    final_matches.sort(key=lambda x: x['score'], reverse=True)
    
    # Return Top 5 for Display
    return final_matches[:5]

def generate_segment_draft(segment_text: str, source_lang: str, target_lang: str, project_id: str, db: Session, threshold=0.4, model_name=None, custom_prompt="", tags=None, cached_matches=None, skip_ai=False, prev_context=None, next_context=None):
    logger.info(f"--- Generate Start: {segment_text[:20]}... Model:{model_name} SkipAI:{skip_ai} ---")
    """
    Generates a draft translation using aligned context.
    If cached_matches is provided, it skips expensive retrieval.
    If skip_ai is True, it returns context matches without generating a draft.
    """
    if not model_name:
        model_name = get_default_model_id()

    # Heuristic: Check for complex tags to trigger Two-Pass Mode
    # Count tags like <1>, <b>, etc.
    tag_count = len(re.findall(r'<[^>]+>', segment_text))
    # Threshold > 3 tags
    is_complex_formatting = tag_count > 3

    # 1. Retrieve Context
    matches = []
    gloss_hits = []
    
    # Use Cache if Available
    if cached_matches is not None:
        matches = cached_matches
        # Ensure we don't duplicate existing MT if re-running
        matches = [m for m in matches if m.get('type') != 'mt']
    else:
        # Expensive DB Search
        matches = search_context_for_segment(segment_text, project_id, db)
        
        # 1.5 Glossary Matches
        try:
            matcher = GlossaryMatcher(project_id, db)
            gloss_hits = matcher.find_matches(segment_text)
            
            for g in gloss_hits:
                # {source, target, note}
                matches.insert(0, {
                     "id": f"glossary-{compute_hash(g['source'])}",
                     "content": f"{g['source']} -> {g['target']}", # Display format
                     "filename": "Glossary", 
                     "type": "glossary",
                     "category": "term",
                     "score": 100,
                     "note": g.get("note")
                })
        except Exception as e:
            print(f"Glossary lookup error: {e}")
    
    # 2. Check for Exact Match (Pre-Translation Optimization)
    # CRITICAL: Ignore glossary terms (they have score 100 but are not full translations)
    best_tm = next((m for m in matches if m.get('type') != 'glossary'), None)
    
    if best_tm and best_tm.get('score', 0) >= 100:
        # Pre-Translation Hit!
        # Skip AI generation.
        return {
            "target_text": best_tm['content'],
            "context_matches": matches,
            "is_exact": True
        }

    # 3. HyDE / Machine Translation Feature
    if skip_ai:
        return {
            "target_text": "", 
            "context_matches": matches,
            "is_exact": False
        }

    mt_draft = ""
    usage_stats = {"input_tokens": 0, "output_tokens": 0}

    try:
        # Construct dynamic system instruction
        system_instruction = f"Translate from {source_lang} to {target_lang}. Output ONLY the raw translation text. No preamble, no markdown formatting, no 'Translation:'."
        system_instruction += " The source text may contain XML-like formatting tags (e.g. <1>...</1>). You MUST include all tags in the translation, but you MAY adjust their position to ensure natural, fluent grammar in the target language. Do NOT break words with tags unnaturally if the source does so."
        
        # TAB HANDLING: Prompt Instruction
        try:
            clean_source = segment_text
            
            # 1. Regex Strip Wrapper Tags around [TAB] (Iterative for nested cases)
            # convert <2><4>[TAB]</4></2> -> [TAB]
            
            # First, normalize [TAB] placeholders
            clean_source = clean_source.replace("\t", "[TAB]")
            
            # Loop to remove layers of tags wrapping [TAB]
            while True:
                prev = clean_source
                clean_source = re.sub(r'<(\d+)>\s*\[TAB\]\s*</\1>', '[TAB]', clean_source, flags=re.IGNORECASE)
                if clean_source == prev:
                    break
            
            # 2. Replace [TAB] with <tab/>
            system_instruction += " Important: The source text contains tab characters represented as <tab/>. You MUST preserve these <tab/> tags in the translation at the appropriate positions."
            clean_source = clean_source.replace("[TAB]", "<tab/>")
                 
        except Exception as e:
            print(f"TAB Handling Error: {e}")
            import traceback
            traceback.print_exc()
            clean_source = segment_text # Fallback
        
        print(f"DEBUG: Clean Source for MT: {repr(clean_source)}")

        # Inject Glossary (Cleaned)
        if gloss_hits:
            system_instruction += "\n\nglossary terms (recommendation, see if they fit the context):"
            for g in gloss_hits:
                # Clean glossary source/target of tab tags too?
                g_src_clean = re.sub(r'<(\d+)>\s*\[TAB\]\s*</\1>', '[TAB]', g['source'], flags=re.IGNORECASE).replace("[TAB]", "<tab/>")
                g_tgt_clean = re.sub(r'<(\d+)>\s*\[TAB\]\s*</\1>', '[TAB]', g['target'], flags=re.IGNORECASE).replace("[TAB]", "<tab/>")
                system_instruction += f"\n- {g_src_clean} -> {g_tgt_clean}"
        
        # Inject Context Matches (Cleaned) to prevent Hallucination
        # matches contains TM hits.
        if matches:
             system_instruction += "\n\nExisting similar translations (Context):"
             for m in matches[:3]: # Top 3
                 if m['type'] == 'mt': continue # Skip previous MT
                 
                 # Clean Content
                 c_content = m['content']
                 # Iterative strip
                 if "[TAB]" in c_content or "\t" in c_content or re.search(r'<(\d+)>', c_content):
                     c_content = c_content.replace("\t", "[TAB]")
                     while True:
                        prev_c = c_content
                        c_content = re.sub(r'<(\d+)>\s*\[TAB\]\s*</\1>', '[TAB]', c_content, flags=re.IGNORECASE)
                        if c_content == prev_c: break
                     c_content = c_content.replace("[TAB]", "<tab/>")
                 
                 system_instruction += f"\n- {c_content}"
                 # Add Score Info
                 score = m.get('score', 0)
                 if score >= 99:
                      system_instruction += f" [MANDATORY MATCH: {score}%]"
                 else:
                      system_instruction += f" [Score: {score}%]"
        
        # Inject Custom Prompt (Technical/Style)
        if custom_prompt and custom_prompt.strip():
            system_instruction += f"\n\nStyle Guide / User Instructions:\n{custom_prompt}"
            
        # Inject Document Context (Neighbors)
        if prev_context or next_context:
             system_instruction += "\n\nContext (Surrounding Text):"
             if prev_context:
                 for p in prev_context: system_instruction += f"\n... {p}"
             
             # The current segment is implicitly the 'Source' below, but clarifying context helps
             system_instruction += f"\n>>> {clean_source} <<<"
             
             if next_context:
                 for n in next_context: system_instruction += f"\n... {n}"

        draft_model = genai.GenerativeModel(model_name)
        
        # TWO-PASS LOGIC vs Standard
        if is_complex_formatting and not skip_ai:
             logger.info(f"Triggering Two-Pass Translation (Tags: {tag_count})")
             
             # Pass 1: Translate Plain
             # Strip all tags for pure linguistic focus
             plain_source = re.sub(r'<[^>]+>', '', clean_source).replace("  ", " ").strip()
             
             # Simple Prompt for Pass 1
             pass1_prompt = f"Translate from {source_lang} to {target_lang}. Output ONLY the raw translation text (Plain Text)."
             
             if custom_prompt and custom_prompt.strip():
                 pass1_prompt += f"\n\nStyle Guide:\n{custom_prompt}"
             
             pass1_prompt += f"\n\nSource: {plain_source}"
             
             # Add Context to Pass 1 too? Yes, usually helpful.
             if prev_context or next_context:
                  pass1_prompt = f"Context:\n" + ("\n".join(prev_context) if prev_context else "") + f"\n>>> {plain_source} <<<\n" + ("\n".join(next_context) if next_context else "") + f"\n\n{pass1_prompt}"

             res1 = draft_model.generate_content(pass1_prompt)
             plain_target = res1.text.strip()
             
             # Track Usage (Pass 1)
             if res1.usage_metadata:
                 usage_stats["input_tokens"] += res1.usage_metadata.prompt_token_count
                 usage_stats["output_tokens"] += res1.usage_metadata.candidates_token_count
             
             # Pass 2: Inject Tags
             pass2_msg = f"""Here is a source sentence with formatting tags: {clean_source}
Here is its translation (Plain Text): {plain_target}

Task: Insert the tags from the source into the translation at the semantically corresponding positions.
Rules:
- You MUST preserve all tags from the source.
- Do NOT translate the content again, just place tags.
- Output ONLY the final tagged translation."""

             if custom_prompt and custom_prompt.strip():
                 pass2_msg += f"\n\nStyle Guide (Constraint): {custom_prompt}"
             
             res2 = draft_model.generate_content(pass2_msg)
             mt_draft = res2.text.strip()
             
             # Track Usage (Pass 2)
             if res2.usage_metadata:
                 usage_stats["input_tokens"] += res2.usage_metadata.prompt_token_count
                 usage_stats["output_tokens"] += res2.usage_metadata.candidates_token_count
             
        else:
             # Standard Single Pass
             res = draft_model.generate_content(f"{system_instruction}\n\nSource: {clean_source}")
             mt_draft = res.text.strip()
             
             # Track Usage (Standard)
             if res.usage_metadata:
                 usage_stats["input_tokens"] += res.usage_metadata.prompt_token_count
                 usage_stats["output_tokens"] += res.usage_metadata.candidates_token_count

        logger.debug(f"raw mt_draft: {mt_draft}")
        
        # TAB HANDLING: Post-process (Restore tabs)
        mt_draft = re.sub(r'<tab\s*/?>', '\t', mt_draft, flags=re.IGNORECASE)
        mt_draft = re.sub(r'</?tab>', '\t', mt_draft, flags=re.IGNORECASE)
        try: logging.info(f"restored mt_draft: {repr(mt_draft)}")
        except: pass

        # Add MT match to list
        if mt_draft:
            matches.insert(0, {
                 "id": "mt-draft",
                 "content": mt_draft,
                 "filename": "Machine Translation", 
                 "type": "mt",
                 "category": "ai",
                 "score": 101 # Always top
            })

    except Exception as e:
        logger.error(f"Generate Error: {e}", exc_info=True)
        return {
            "target_text": "",
            "context_matches": matches, 
            "is_exact": False,
            "error": str(e)
        }
    
    # 4. Generate Final Draft
    return {
        "target_text": mt_draft, 
        "context_matches": matches,
        "context_matches": matches,
        "is_exact": False,
        "usage": usage_stats
    }

def generate_project_drafts(project_id: str):
    from .database import SessionLocal
    from .models import Segment, Project
    
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project: return
        
        segments = db.query(Segment).filter(Segment.project_id == project_id).all()
        config = project.config or {}
        ai_settings = config.get("ai_settings", {})
        model = ai_settings.get("model") or get_default_model_id()
        custom_prompt = ai_settings.get("custom_prompt", "")
        
        print(f"Generating drafts for project {project_id} (Model: {model})...")
        
        for seg in segments:
            try:
                # Updated Pipeline Call
                res = generate_segment_draft(
                    segment_text=seg.source_content,
                    source_lang=project.source_lang,
                    target_lang=project.target_lang,
                    project_id=project_id,
                    db=db,
                    model_name=model,
                    custom_prompt=custom_prompt
                )
                
                current_meta = dict(seg.metadata_json or {})
                current_meta['context_matches'] = res['context_matches']
                current_meta['ai_draft'] = res["target_text"]
                seg.metadata_json = current_meta
                
                # Pre-Translation Logic:
                # If exact match, fill target content directly!
                if res.get('is_exact', False):
                     seg.target_content = res["target_text"]
                
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(seg, "metadata_json")

            except Exception as se:
                print(f"Error seg {seg.id}: {se}")
        
        db.commit()
        print(f"Draft generation complete.")
        
    except Exception as e:
        print(f"Error drafts: {e}")
    finally:
        db.close()
