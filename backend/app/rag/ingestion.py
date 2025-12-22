import logging
import os
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from ..models import Project, ProjectFile, ContextChunk, ProjectFileCategory, TranslationUnit, TranslationOrigin
from ..storage import download_file
from ..parser import parse_docx
from ..tmx import parse_tmx_units, compute_hash, ingest_tmx_direct
from .retrieval import RetrievalEngine

logger = logging.getLogger("RAG.Ingest")

def ingest_project_files(project_id: str, db: Session):
    """
    Refactored ingestion task.
    Populates ContextChunk with chunk_index.
    """
    engine = RetrievalEngine() # Ensure models loaded
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project: return
    
    project.rag_status = "ingesting"
    db.commit()
    
    log_messages = []
    def log(msg):
        logger.info(msg)
        log_messages.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
        project.ingestion_logs = list(log_messages) # Copy
        db.commit()

    try:
        if not engine._bi_encoder:
             log("FATAL: Encoder not loaded.")
             return

        files = db.query(ProjectFile).filter(
            ProjectFile.project_id == project_id,
            ProjectFile.category.in_([ProjectFileCategory.legal.value, ProjectFileCategory.background.value])
        ).all()
        
        log(f"Found {len(files)} context files.")
        
        total_chunks = 0
        BATCH_SIZE = 32
        
        for file in files:
            log(f"Processing {file.filename}...")
            temp_path = f"temp_rag_{file.id}_{file.filename}"
            
            try:
                download_file(file.file_path, temp_path)
                
                chunks_to_persist = []
                
                # DOCX Handler
                if file.filename.endswith(".docx"):
                     # ... (Use parse_docx logic from legacy)
                     # For simplicity, using standard parser
                     segments = parse_docx(temp_path)
                     
                     # Convert to chunks with Index
                     for idx, seg in enumerate(segments):
                         txt = seg.source_text.strip()
                         if len(txt) > 3:
                             chunks_to_persist.append({
                                 "text": txt,
                                 "rich": txt, # DOCX usually plain, but if parser supports rich, use it
                                 "index": idx
                             })
                             
                # TMX Handler
                elif file.filename.endswith(".tmx"):
                     # Adapt TMX logic
                     # TMX implies alignment. We ingest as ContextChunks AND TranslationUnits?
                     # Legacy rag.py did both.
                     log("Ingesting TMX...")
                     # Direct TMX ingest for TM (Exact Match)
                     origin = TranslationOrigin.mandatory if file.category == "legal" else TranslationOrigin.optional
                     ingest_tmx_direct(temp_path, project_id, origin, db)
                     
                     # Also ingest as Vectors (Chunks)
                     # We treat each TU as a chunk.
                     # Index is sequential in file.
                     idx = 0
                     for unit in parse_tmx_units(temp_path):
                         chunks_to_persist.append({
                             "text": unit['source_text'],
                             "rich": unit['target_text'], # Store target in rich_content
                             "index": idx
                         })
                         idx += 1
                
                # Batch Embed & Insert
                for i in range(0, len(chunks_to_persist), BATCH_SIZE):
                    batch = chunks_to_persist[i : i+BATCH_SIZE]
                    texts = [engine.clean_tags(b['text']) for b in batch]
                    
                    try:
                        embeddings = engine._bi_encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
                    except Exception as e:
                        log(f"Embedding error: {e}")
                        continue
                        
                    db_objs = []
                    for b, vec in zip(batch, embeddings):
                        db_objs.append(ContextChunk(
                            file_id=file.id,
                            content=b['text'],
                            rich_content=b['rich'],
                            embedding=vec.tolist(),
                            chunk_index=b['index'] # <--- NEW
                        ))
                    
                    db.add_all(db_objs)
                    db.commit()
                    total_chunks += len(batch)
                    
            except Exception as e:
                log(f"Error file {file.filename}: {e}")
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
                
        project.rag_status = "ready"
        log(f"Ingestion complete. {total_chunks} vectors.")
        
    except Exception as e:
        log(f"Fatal Ingestion Error: {e}")
        project.rag_status = "error"
    finally:
        db.commit()
