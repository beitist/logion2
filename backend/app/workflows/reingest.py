import os
import logging
from ..models import ProjectFile, ContextChunk, ProjectFileCategory, TranslationOrigin, Segment
from ..storage import download_file
from ..parser import parse_docx
from ..tmx import parse_tmx_units, ingest_tmx_direct
from ..rag.retrieval import RetrievalEngine
from ..database import SessionLocal
from .base import BaseWorkflow

# Reuse logger from ingestion or new one? BaseWorkflow uses "Workflow".
# We can subclass logger name if needed.

class ReingestWorkflow(BaseWorkflow):
    def run(self):
        """
        Core Ingestion Logic.
        Implements Two-Pass Logic: 
        1. Parse all files & Count Chunks.
        2. Embed & Insert with Progress Updates.
        """
        # Set Status
        self.project.rag_status = "ingesting"
        self.project.rag_progress = 0
        self.db.commit()
        
        # Clear Logs?
        self.project.ingestion_logs = []
        self.log("Initializing RAG Engine (Loading Models)...")
        
        engine = RetrievalEngine() 
        if not engine._client:
            self.log("FATAL: Voyage AI Client not loaded (Check API Key).")
            self.fail(Exception("Voyage AI Client missing"))
            return

        files = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == self.project_id,
            ProjectFile.category.in_([ProjectFileCategory.legal.value, ProjectFileCategory.background.value])
        ).all()
        
        self.log(f"Found {len(files)} context files. Starting Phase 1: Parsing...")
        
        # --- Phase 1: Parse & Prepare (In Memory) ---
        all_chunks_to_persist = []
        
        for file in files:
            temp_path = f"temp_rag_{file.id}_{file.filename}"
            try:
                download_file(file.file_path, temp_path)
                
                # DOCX Handler
                if file.filename.endswith(".docx"):
                        segments = parse_docx(temp_path)
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
                        self.log(f"Processing TMX {file.filename}...")
                        origin = TranslationOrigin.mandatory if file.category == "legal" else TranslationOrigin.optional
                        ingest_tmx_direct(temp_path, self.project_id, origin, self.db)
                        
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
                self.log(f"Error parsing {file.filename}: {e}")
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
        
        total_chunks = len(all_chunks_to_persist)
        
        # --- Phase 2: Embed & Insert ---
        BATCH_SIZE = 32
        processed = 0
        
        # Calculate Total Work (Chunks + Segments)
        segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).all()
        total_segments = len(segments)
        
        total_work = total_chunks + total_segments
        self.log(f"Phase 1 Complete. Total Work: {total_chunks} chunks + {total_segments} segments = {total_work} vectors.")
    
        if total_work == 0:
            self.update_progress(100, status="ready")
            return

        # 1. Chunks
        for i in range(0, total_chunks, BATCH_SIZE):
            batch = all_chunks_to_persist[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(b['text']) for b in batch]
            
            try:
                embeddings = engine.embed_batch(texts, input_type="document")
            except Exception as e:
                self.log(f"Embedding error: {e}")
                continue
                
            db_objs = []
            for b, vec in zip(batch, embeddings):
                db_objs.append(ContextChunk(
                    file_id=b['file_id'],
                    content=b['text'],
                    rich_content=b['rich'],
                    embedding=vec,
                    chunk_index=b['index']
                ))
            
            self.db.add_all(db_objs)
            self.db.commit()
            
            processed += len(batch)
            progress = int((processed / total_work) * 100)
            self.update_progress(progress)
            
            if i % (BATCH_SIZE * 5) == 0:
                self.log(f"Vectorized {processed}/{total_work} items...")
        
        # 2. Segments (Phase 3) - Same logic as ReinitializeWorkflow.embed_segments
        self.log("Starting Phase 3: Pre-vectorizing Source Segments...")
        
        for i in range(0, total_segments, BATCH_SIZE):
            batch_segs = segments[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(s.source_content) for s in batch_segs]
            
            try:
                embeddings = engine.embed_batch(texts, input_type="document")
                
                for s, vec in zip(batch_segs, embeddings):
                    s.embedding = vec
                
                self.db.commit() # Save updates
                
                processed += len(batch_segs)
                progress = int((processed / total_work) * 100)
                self.update_progress(progress)
                
            except Exception as e:
                self.log(f"Segment embedding error: {e}")
    
        self.update_progress(100, status="ready")
        self.log(f"Ingestion complete. {total_work} vectors stored.")


def run_background_reingest(project_id: str):
    """
    Background Task Entrypoint.
    """
    db = SessionLocal()
    try:
        wf = ReingestWorkflow(db, project_id)
        wf.run()
    except Exception as e:
        # Fallback logging
        logging.getLogger("Workflow").error(f"Reingest Failed: {e}")
        # Try to set error status
        try:
             project = db.query(to_model_class("Project")).filter(to_model_class("Project").id == project_id).first()
             if project:
                 project.rag_status = "error"
                 db.commit()
        except:
            pass
    finally:
        db.close()

# Helper to avoid circular imports? BaseWorkflow imports Project.
# run_background_reingest uses SessionLocal, so it is fine.
# Wait, `to_model_class` wrapper? No, just import Project.
from ..models import Project
