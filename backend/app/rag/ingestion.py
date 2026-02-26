import logging
import os
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from ..models import Project, ProjectFile, ContextChunk, ProjectFileCategory, TranslationUnit, TranslationOrigin, Segment
from ..storage import download_file
from ..document.parser import parse_document
from ..tmx import parse_tmx_units, compute_hash, ingest_tmx_direct
from .retrieval import RetrievalEngine
from ..database import SessionLocal

logger = logging.getLogger("RAG.Ingest")

def ingest_project_files(project_id: str):
    """
    Background Task Wrapper.
    Creates a new DB session and delegates to the logic handler.
    Ensures safe session cleanup.
    """
    db = SessionLocal()
    try:
        _ingest_logic(project_id, db)
    except Exception as e:
        logger.error(f"Fatal Ingestion Error: {e}")
        try:
             project = db.query(Project).filter(Project.id == project_id).first()
             if project:
                 project.rag_status = "error"
                 db.commit()
        except:
             pass
    finally:
        db.close()

def _ingest_logic(project_id: str, db: Session):
    """
    Core Ingestion Logic.
    Implements Two-Pass Logic: 
    1. Parse all files & Count Chunks.
    2. Embed & Insert with Progress Updates.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project: return
    
    project.rag_status = "ingesting"
    project.rag_progress = 0
    db.commit()
    
    # helper for logging to DB
    log_messages = []
    def log(msg):
        logger.info(msg)
        display_msg = f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}"
        log_messages.append(display_msg)
        # Refresh project to avoid stale object if committed elsewhere
        project.ingestion_logs = list(log_messages) 
        db.commit()

    def update_progress(p):
        project.rag_progress = int(p)
        db.commit()

    log("Initializing RAG Engine (Loading Models)...")
    
    engine = RetrievalEngine() # Load models now
    
    if not engine._client:
        log("FATAL: Voyage AI Client not loaded (Check API Key).")
        project.rag_status = "error"
        db.commit()
        return

    files = db.query(ProjectFile).filter(
        ProjectFile.project_id == project_id,
        ProjectFile.category.in_([ProjectFileCategory.legal.value, ProjectFileCategory.background.value])
    ).all()
    
    log(f"Found {len(files)} context files. Starting Phase 1: Parsing...")

    # --- Cleanup: Delete ALL old chunks & non-user TM units for this project ---
    from sqlalchemy import select
    all_file_ids = select(ProjectFile.id).where(ProjectFile.project_id == project_id)
    old_chunks = db.query(ContextChunk).filter(
        ContextChunk.file_id.in_(all_file_ids)
    ).delete(synchronize_session=False)
    old_tus = db.query(TranslationUnit).filter(
        TranslationUnit.project_id == project_id,
        TranslationUnit.origin_type != TranslationOrigin.user.value
    ).delete(synchronize_session=False)
    db.commit()
    log(f"Cleanup: Removed {old_chunks} old chunks + {old_tus} old TM units.")

    # --- Phase 1: Parse & Prepare (In Memory) ---
    # We parse all files to get the Total Chunk Count for proper progress bars.

    all_chunks_to_persist = []
    
    for file in files:
        temp_path = f"temp_rag_{file.id}_{file.filename}"
        try:
            download_file(file.file_path, temp_path)
            
            # DOCX Handler
            if file.filename.endswith(".docx"):
                    segments = parse_document(temp_path)
                    for idx, seg in enumerate(segments):
                        txt = seg.source_text.strip()
                        if len(txt) > 3:
                            all_chunks_to_persist.append({
                                "file_id": file.id,
                                "text": txt,
                                "rich": txt, 
                                "index": idx
                            })
                            
            # TMX Handler
            elif file.filename.endswith(".tmx"):
                    # Direct TMX ingest for TM (Exact Match)
                    log(f"Processing TMX {file.filename}...")
                    origin = TranslationOrigin.mandatory if file.category == "legal" else TranslationOrigin.optional
                    ingest_tmx_direct(temp_path, project_id, origin, db)
                    
                    # Also ingest as Vectors
                    idx = 0
                    for unit in parse_tmx_units(temp_path):
                        all_chunks_to_persist.append({
                            "file_id": file.id,
                            "text": unit['source_text'],
                            "rich": unit['target_text'], 
                            "index": idx
                        })
                        idx += 1
                        
        except Exception as e:
            log(f"Error parsing {file.filename}: {e}")
        finally:
            if os.path.exists(temp_path): os.remove(temp_path)
    
    total_chunks = len(all_chunks_to_persist)
    log(f"Phase 1 Complete. Total Vectors to generate: {total_chunks}")
    
    # --- Phase 2: Embed & Insert ---
    
    BATCH_SIZE = 32
    processed = 0
    
    # Calculate Total Work (Chunks + Segments)
    segments = db.query(Segment).filter(Segment.project_id == project_id).all()
    total_segments = len(segments)
    
    total_work = total_chunks + total_segments
    log(f"Phase 1 Complete. Total Work: {total_chunks} chunks + {total_segments} segments = {total_work} vectors.")

    if total_work == 0:
        update_progress(100)
    else:
        # 1. Chunks
        for i in range(0, total_chunks, BATCH_SIZE):
            batch = all_chunks_to_persist[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(b['text']) for b in batch]
            
            try:
                # Use "document" for storage
                embeddings = engine.embed_batch(texts, input_type="document")
            except Exception as e:
                log(f"Embedding error: {e}")
                continue
                
            db_objs = []
            for b, vec in zip(batch, embeddings):
                db_objs.append(ContextChunk(
                    file_id=b['file_id'], # Use stored file_id
                    content=b['text'],
                    rich_content=b['rich'],
                    embedding=vec, # Already list[float]
                    chunk_index=b['index']
                ))
            
            db.add_all(db_objs)
            db.commit()
            
            processed += len(batch)
            progress = int((processed / total_work) * 100)
            update_progress(progress)
            
            if i % (BATCH_SIZE * 5) == 0:
                log(f"Vectorized {processed}/{total_work} items...")
        
        # 2. Segments (Phase 3)
        log("Starting Phase 3: Pre-vectorizing Source Segments...")
        
        # We need to process existing SQL objects. 
        # Ideally we iterate by batches to avoid massive RAM if thousands of segments.
        for i in range(0, total_segments, BATCH_SIZE):
            batch_segs = segments[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(s.source_content) for s in batch_segs]
            
            try:
                embeddings = engine.embed_batch(texts, input_type="document")
                
                for s, vec in zip(batch_segs, embeddings):
                    s.embedding = vec
                
                db.commit() # Save updates
                
                processed += len(batch_segs)
                progress = int((processed / total_work) * 100)
                update_progress(progress)
                
            except Exception as e:
                log(f"Segment embedding error: {e}")
    
    project.rag_status = "ready"
    project.rag_progress = 100
    log(f"Ingestion complete. {total_work} vectors stored.")

def embed_project_segments(project_id: str):
    """
    Background Task: Re-generates vectors ONLY for segments (Source Content).
    Used after Reinitialize.
    """
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project: return

        logger.info(f"Starting Segment Embedding for {project_id}")
        
        # helper
        def log(msg):
            # We append to existing logs? Or clear? Reinit usually keeps logs?
            # Let's append.
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
            if not project.ingestion_logs: project.ingestion_logs = []
            project.ingestion_logs = project.ingestion_logs + [f"[{timestamp}] {msg}"]
            db.commit()

        def update_progress(p):
            project.rag_progress = int(p)
            db.commit()

        # Logic matches Phase 3 of _ingest_logic
        engine = RetrievalEngine()
        if not engine._client:
             log("Error: Voyage AI not loaded.")
             return

        segments = db.query(Segment).filter(Segment.project_id == project_id).all()
        total = len(segments)
        BATCH_SIZE = 32
        processed = 0
        
        log(f"Generating vectors for {total} segments...")
        
        for i in range(0, total, BATCH_SIZE):
            batch_segs = segments[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(s.source_content) for s in batch_segs]
            
            try:
                # Use "document" for storage
                embeddings = engine.embed_batch(texts, input_type="document")
                
                # Update DB objects
                for s, vec in zip(batch_segs, embeddings):
                    s.embedding = vec
                
                db.commit() 
                
                processed += len(batch_segs)
                progress = int((processed / total) * 100)
                update_progress(progress)
                
            except Exception as e:
                log(f"Embedding error: {e}")
                
        project.rag_status = "ready"
        update_progress(100)
        log("Segment vectors updated.")
        
    except Exception as e:
        logger.error(f"Segment Embedding Error: {e}")
    finally:
        db.close()
