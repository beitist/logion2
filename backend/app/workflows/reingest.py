import os
import logging
from ..models import ProjectFile, ContextChunk, ProjectFileCategory, TranslationOrigin, TranslationUnit, Segment
from ..storage import download_file
from ..document.parser import parse_document
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
        
        self.log(f"Found {len(files)} context files.")

        # --- Cleanup: Delete ALL old chunks & non-user TM units for this project ---
        # Use subquery to catch chunks from deleted/recategorized files too
        from sqlalchemy import select
        all_file_ids = select(ProjectFile.id).where(ProjectFile.project_id == self.project_id)
        old_chunks = self.db.query(ContextChunk).filter(
            ContextChunk.file_id.in_(all_file_ids)
        ).delete(synchronize_session=False)
        old_tus = self.db.query(TranslationUnit).filter(
            TranslationUnit.project_id == self.project_id,
            TranslationUnit.origin_type != TranslationOrigin.user.value
        ).delete(synchronize_session=False)
        self.db.commit()
        self.log(f"Cleanup: Removed {old_chunks} old chunks + {old_tus} old TM units.")

        self.log("Starting Phase 1: Parsing...")

        # --- Phase 1: Parse & Prepare (In Memory) ---
        all_chunks_to_persist = []
        
        for file in files:
            temp_path = f"temp_rag_{file.id}_{file.filename}"
            try:
                # Optimized: We assume process_file_parsing handles documents.
                # Only download manually for TMX or fallback.
                
                is_doc = file.filename.lower().endswith((".docx", ".xlsx"))
                
                if not is_doc:
                     download_file(file.file_path, temp_path)
                
                # Document Handler (DOCX + XLSX)
                if file.filename.lower().endswith((".docx", ".xlsx")):
                        from ..document.parsing_service import process_file_parsing
                        # Logic handles download internally
                        segments = process_file_parsing(
                             file_path_or_url=file.file_path,
                             project_id=self.project_id, # Reuse project ID, sequential processing is safe
                             original_filename=file.filename
                        )
                        
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

        # Phase 2: Vectorize Context Chunks
        self.log(f"Phase 2: Vectorizing {total_chunks} context chunks...")
        total_tokens = 0

        for i in range(0, total_chunks, BATCH_SIZE):
            batch = all_chunks_to_persist[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(b['text']) for b in batch]

            try:
                embeddings, tokens = engine.embed_batch(texts, input_type="document")
                total_tokens += tokens
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

        self.log(f"Phase 2 Complete. {total_chunks} chunks vectorized.")

        # Phase 3: Vectorize Source Segments
        self.log(f"Phase 3: Vectorizing {total_segments} source segments...")

        for i in range(0, total_segments, BATCH_SIZE):
            batch_segs = segments[i : i+BATCH_SIZE]
            texts = [engine.clean_tags(s.source_content) for s in batch_segs]

            try:
                embeddings, tokens = engine.embed_batch(texts, input_type="document")
                total_tokens += tokens

                for s, vec in zip(batch_segs, embeddings):
                    s.embedding = vec

                self.db.commit()

                processed += len(batch_segs)
                progress = int((processed / total_work) * 100)
                self.update_progress(progress)

                if i % (BATCH_SIZE * 5) == 0:
                    self.log(f"Vectorized {processed}/{total_work} items...")

            except Exception as e:
                self.log(f"Segment embedding error: {e}")

        self.log(f"Phase 3 Complete. {total_segments} segments vectorized.")
    
        # Update Usage Stats
        if total_tokens > 0:
            current_config = dict(self.project.config or {})
            usage_stats = current_config.get("usage_stats", {})
            m_stats = usage_stats.get("voyage-3-large", {"input_tokens": 0, "output_tokens": 0})
            
            m_stats["input_tokens"] += total_tokens
            
            usage_stats["voyage-3-large"] = m_stats
            current_config["usage_stats"] = usage_stats
            self.project.config = current_config
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(self.project, "config")
            self.db.commit()

        self.update_progress(100, status="ready")
        self.log(f"Ingestion complete. {total_work} vectors stored. ({total_tokens} tokens)")


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
