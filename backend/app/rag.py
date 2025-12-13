from .tmx import compute_hash, normalize_text
from .models import TranslationUnit, TranslationOrigin
import os
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

load_dotenv()

# Configure Gemini (Still used for generative tasks)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# --- LOAD LOCAL MODELS ---
# We load them once at startup.
# Check for MPS (Apple Silicon)
device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Loading Models on {device}...")

try:
    # 1. Bi-Encoder (LaBSE) - 768 Dimensions
    # Using 'sentence-transformers/LaBSE'
    _bi_encoder = SentenceTransformer('sentence-transformers/LaBSE', device=device)
    
    # 2. Cross-Encoder (Reranking)
    # Using 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
    _cross_encoder = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', device=device)
    
    print("✅ Models Loaded Successfully.")
    
    # 3. Semantic Aligner (SpaCy + Vectors)
    from .aligner import SemanticAligner
    _aligner = SemanticAligner(_bi_encoder)
    
except Exception as e:
    print(f"❌ Error loading models: {e}")
    _bi_encoder = None
    _cross_encoder = None
    _aligner = None

def extract_text_from_docx(docx_path):
    try:
        text_content = []
        with zipfile.ZipFile(docx_path) as z:
            xml_content = z.read("word/document.xml")
            tree = ElementTree.fromstring(xml_content)
            NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for p in tree.iter(f"{NS}p"):
                texts = [node.text for node in p.iter(f"{NS}t") if node.text]
                if texts:
                    text_content.append("".join(texts))
        return "\n".join(text_content)
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# Initialize Segmenter
_segmenter = pysbd.Segmenter(language="en", clean=False)


# --- Ingestion ---

from .database import SessionLocal

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
        print(msg)
        try:
             p = db.query(Project).filter(Project.id == project_id).first()
             current_logs = list(p.ingestion_logs) if p.ingestion_logs else []
             from datetime import datetime
             current_logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
             p.ingestion_logs = current_logs
             db.commit()
        except Exception as e:
             print(f"Log error: {e}")

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
                        texts = [b['text'] for b in batch]
                        embeddings = _bi_encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
                        
                        db_chunks = []
                        for b, vec in zip(batch, embeddings):
                            db_chunks.append(ContextChunk(
                                file_id=file_record.id,
                                content=b['text'],
                                rich_content=b['rich'],
                                embedding=vec.tolist(),
                                source_segment=b['src_seg'],
                                target_segment=b['tgt_seg'],
                                alignment_score=b['score'],
                                alignment_type=b['type']
                            ))
                        db.add_all(db_chunks)
                        db.commit()
                        total_chunks += len(batch)
                        
                    continue
                
                if file_record.filename.endswith(".docx"):
                    raw_text = extract_text_from_docx(temp_path)
                else: 
                    raw_text = "" # Add PDF support later if needed
                    
                if not raw_text:
                    log_msg(f"Skipping {file_record.filename} (empty or unsupported)")
                    continue
                
                # 3. Sentence Splitting (TM-like)
                chunks = []
                paragraphs = raw_text.split('\n')
                for p in paragraphs:
                    p_clean = clean_text(p)
                    if p_clean:
                        try:
                            sents = _segmenter.segment(p_clean)
                        except:
                            sents = [p_clean]
                        
                        for s in sents:
                            if len(s.strip()) > 3:
                                chunks.append(s.strip())
                
                log_msg(f"Generated {len(chunks)} sentence segments (Granular). Encoding...")
                
                # 4. Embed & Store
                for i in range(0, len(chunks), BATCH_SIZE):
                    batch = chunks[i : i + BATCH_SIZE]
                    
                    # LaBSE Encoding
                    embeddings = _bi_encoder.encode(batch, convert_to_numpy=True, normalize_embeddings=True)
                    
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
                        
            except Exception as e:
                log_msg(f"ERROR processing {file_record.filename}: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)


        project.rag_status = "ready"
        log_msg(f"RAG READY. Knowledge base refreshed: {total_chunks} alignment vectors.")
        
        # Trigger Auto-Draft
        log_msg("Starting automatic draft generation...")
        generate_project_drafts(project_id)
        
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

def extract_numbers(text):
    return set(re.findall(r'\d+', text))

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
        print(f"TM Lookup Error: {e}")

    if not _bi_encoder:
        return exact_matches

    # 1. Bi-Encoder Retrieval (Recall)
    try:
        # Encode Query (Source English)
        query_vector = _bi_encoder.encode(segment_text, normalize_embeddings=True).tolist()
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
        print(f"Reranking error: {e}")
        import numpy as np
        scores = np.zeros(len(candidates)) # Fallback
    
    # 3. Heuristics & Number Penalty
    final_matches = []
    
    query_numbers = extract_numbers(segment_text)
    
    for idx, (chunk, file) in enumerate(results):
        base_score = float(scores[idx]) # Logit score (approx -10 to 10)
        
        # Number Penalty
        chunk_numbers = extract_numbers(chunk.content)
        missing_numbers = query_numbers - chunk_numbers
        
        penalty = 0.0
        if missing_numbers:
             penalty = 5.0 # Massive penalty for missing numbers
             
        final_score_logit = base_score - penalty
        
        # Convert Logit to UI Score (0-100)
        # Calibration (Phase 7):
        # We want strong semantic matches (Logit > 2.5) to appear green (> 90%).
        # Old formula: offset 1.5 -> Logit 3.0 = 81%. Too low.
        # New formula: offset 0.5 -> Logit 3.0 = 92%.
        # Boost: If Logit > 4.0 -> 98-99%.
        
        import math
        
        if final_score_logit > 4.0:
            ui_score = 99 # Near perfect interaction
        elif final_score_logit > 2.5:
             # Aggressive sigmoid for good matches
             # Logit 2.5 -> 1 / (1 + exp(-(2.5))) = 92%
             ui_score = 1 / (1 + math.exp(-(final_score_logit - 0.0))) * 100
        else:
             # Standard curve for weaker matches
             # Logit 0.0 -> 50%
             # Logit 1.8 (our case) -> 86%
             ui_score = 1 / (1 + math.exp(-(final_score_logit - 0.0))) * 100
        
        if final_score_logit < -2.0: 
            continue # Filter out completely
            
        match_type = "mandatory" if file.category == "legal" else "optional"
        
        # Use Rich Content (with Tags) if available, else plain content
        display_content = chunk.rich_content if chunk.rich_content else chunk.content
        
        final_matches.append({
            "id": chunk.id,
            "content": display_content,
            "filename": file.filename,
            "type": match_type,
            "category": file.category,
            "score": int(ui_score), # Integer format
            "raw_logit": final_score_logit
        })

    # Sort by Final UI Score
    final_matches.sort(key=lambda x: x['score'], reverse=True)
    
    # Return Top 5 for Display
    return final_matches[:5]

def generate_segment_draft(segment_text: str, source_lang: str, target_lang: str, project_id: str, db: Session, threshold=0.4, model_name="gemini-2.0-flash", custom_prompt=""):
    """
    Generates a draft translation using aligned context.
    """
    # 1. Retrieve Context (New Pipeline)
    matches = search_context_for_segment(segment_text, project_id, db)
    
    # 2. Check for Exact Match (Pre-Translation Optimization)
    top_match = matches[0] if matches else None
    if top_match and top_match.get('score', 0) >= 100:
        # Pre-Translation Hit!
        # Skip AI generation.
        return {
            "target_text": top_match['content'],
            "context_matches": matches,
            "is_exact": True
        }

    # 3. HyDE / Machine Translation Feature
    mt_draft = ""
    try:
        # Construct dynamic system instruction
        system_instruction = f"Translate from {source_lang} to {target_lang}. Output ONLY the raw translation text. No preamble, no markdown formatting, no 'Translation:'."
        
        # Inject Custom Prompt (Technical/Style)
        if custom_prompt and custom_prompt.strip():
            system_instruction += f"\n\nStyle Guide / User Instructions:\n{custom_prompt}"
            
        draft_model = genai.GenerativeModel(model_name)
        res = draft_model.generate_content(f"{system_instruction}\n\nSource: {segment_text}")
        mt_draft = res.text.strip()
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
    except:
        pass
    
    # 4. Generate Final Draft
    return {
        "target_text": mt_draft, 
        "context_matches": matches,
        "is_exact": False
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
        model = ai_settings.get("model", "gemini-2.0-flash")
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
