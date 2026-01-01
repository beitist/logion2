import os
import datetime
from collections import defaultdict, deque
from typing import Optional, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from ..models import Project, Segment, ProjectFile, ProjectFileCategory, AiUsageLog
from ..storage import download_file
from ..document.parser import parse_document
from ..rag.retrieval import RetrievalEngine
from .base import BaseWorkflow
from ..database import SessionLocal

UPLOAD_DIR = "uploads"

def run_background_vector_regen(project_id: str):
    """
    Background Task Entrypoint.
    Creates a new session for the workflow to run safely in background.
    """
    db = SessionLocal()
    try:
        wf = ReinitializeWorkflow(db, project_id)
        wf.embed_segments()
    except Exception as e:
        # Fallback logging if workflow init failed
        print(f"Background Vector Regen Failed: {e}")
    finally:
        db.close()

class ReinitializeWorkflow(BaseWorkflow):
    def run(self, new_file_upload: Optional[Any] = None) -> Project:
        """
        Main entry point for Reinitialization.
        1. Replace File (Optional)
        2. Re-parse & Merge
        3. Trigger Vector Embed (Sync or Async? Background task usually calls this?)
           Actually, the service calls us. We do the heavy lifing here.
           The BACKGROUND vector regen should be a separate method we can call via BackgroundTasks?
           Or we just do the synchronous part here and let the Service trigger the background part?
           
           Better: The Service triggers `run_background_embedding`.
           This `run` method does the core logic (Steps 1-7 from before).
        """
        
        # 1. Find Source File
        # We access self.project (loaded in BaseWorkflow)
        if not self.project:
            raise HTTPException(status_code=404, detail="Project not found")

        source_record = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == self.project_id,
            ProjectFile.category == ProjectFileCategory.source.value
        ).first()
        
        if not source_record and not new_file_upload:
             raise HTTPException(status_code=400, detail="No source file found to reinitialize.")
            
        # 1.5. Replace File if provided
        if new_file_upload:
            try:
                # If no record exists, we might crash accessing source_record.file_path
                # But we assume structure exists.
                if not source_record:
                     # This scenario implies project structure is broken or very new
                     pass 
                
                content = new_file_upload.file.read()
                # Overwrite on disk
                with open(source_record.file_path, "wb") as f:
                    f.write(content)
                
                # Update DB
                source_record.filename = new_file_upload.filename
                source_record.uploaded_at = datetime.utcnow()
                self.db.add(source_record)
                self.db.commit()
                self.log(f"Replaced source file with {new_file_upload.filename}")
                
            except Exception as e:
                 self.fail(e)
                 raise HTTPException(status_code=500, detail=f"Failed to save new source file: {e}")

        # 2. Parse (Fresh)
        new_segments_internal = []
        try:
            from ..document.parsing_service import process_file_parsing
            
            new_segments_internal = process_file_parsing(
                file_path_or_url=source_record.file_path,
                project_id=self.project_id,
                source_lang=self.project.source_lang,
                original_filename=source_record.filename
            )
            
        except Exception as e:
            self.fail(e)
            raise HTTPException(status_code=500, detail=f"Reinitialization parsing failed: {e}")

        # 3. Merge
        final_db_segments = self._merge_old_with_new(new_segments_internal)

        # 4. Atomic Replace
        try:
            # Unlink AI Usage Logs
            self.db.query(AiUsageLog).filter(
                AiUsageLog.project_id == self.project_id
            ).update({AiUsageLog.segment_id: None}, synchronize_session=False)

            # Delete old
            self.db.query(Segment).filter(Segment.project_id == self.project_id).delete()
            
            # Insert new
            self.db.add_all(final_db_segments)
            
            # Set Status for Next Step (Vector Gen)
            self.project.rag_status = "ingesting"
            self.project.rag_progress = 0
            self.log("Reinitialization successful. Starting vector regeneration...")
            
            self.db.commit()
            self.db.refresh(self.project)
            
            return self.project
            
        except Exception as e:
            self.db.rollback()
            self.fail(e)
            raise HTTPException(status_code=500, detail=f"Database update failed: {e}")

    def _merge_old_with_new(self, new_segments_internal):
        """
        Merges existing segments (DB) with new parsed segments.
        Private helper.
        """
        old_segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).order_by(Segment.index).all()
        
        # Map Source Text -> Queue
        old_map = defaultdict(deque)
        for seg in old_segments:
            old_map[seg.source_content].append(seg)
            
        self.log(f"Parsed {len(new_segments_internal)} new segments vs {len(old_segments)} old.")

        final_db_segments = []
        new_count = 0
        preserved_count = 0
        
        for i, new_seg_int in enumerate(new_segments_internal):
            target_content = None
            status = "draft"
            
            if old_map[new_seg_int.source_text]:
                match = old_map[new_seg_int.source_text].popleft()
                target_content = match.target_content
                status = match.status
                preserved_count += 1
            else:
                new_count += 1
            
            seg_dump = new_seg_int.model_dump()
            
            new_db_seg = Segment(
                id=new_seg_int.segment_id,
                project_id=self.project_id,
                index=i,
                source_content=new_seg_int.source_text,
                target_content=target_content,
                status=status,
                metadata_json=seg_dump
            )
            final_db_segments.append(new_db_seg)
            
        self.log(f"Reinit Merge: Preserved {preserved_count}, Added {new_count}. Total {len(final_db_segments)}.")
        return final_db_segments

    def embed_segments(self):
        """
        Background Task Logic.
        Regenerates vectors for all segments.
        """
        try:
            self.log("Starting Segment Vector Regeneration...")
            
            engine = RetrievalEngine()
            if not engine._client:
                 self.log("Error: Voyage AI not loaded.")
                 self.project.rag_status = "error"
                 self.db.commit()
                 return

            segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).all()
            total = len(segments)
            BATCH_SIZE = 32
            processed = 0
            
            total_tokens = 0
            
            for i in range(0, total, BATCH_SIZE):
                batch_segs = segments[i : i+BATCH_SIZE]
                texts = [engine.clean_tags(s.source_content) for s in batch_segs]
                
                try:
                    embeddings, tokens = engine.embed_batch(texts, input_type="document")
                    total_tokens += tokens
                    
                    for s, vec in zip(batch_segs, embeddings):
                        # Ensure list type for JSON serialization if needed, or straight vec for PGVector
                        # PGVector handles list[float].
                        s.embedding = vec
                    
                    self.db.commit()
                    
                    processed += len(batch_segs)
                    progress = int((processed / total) * 100)
                    self.update_progress(progress)
                    
                except Exception as e:
                    self.log(f"Embedding error batch {i}: {e}")
                    
            # Update Usage Stats
            if total_tokens > 0:
                current_config = dict(self.project.config or {})
                usage_stats = current_config.get("usage_stats", {})
                m_stats = usage_stats.get("voyage-3-large", {"input_tokens": 0, "output_tokens": 0})
                
                m_stats["input_tokens"] += total_tokens
                # output is 0 for embedding
                
                usage_stats["voyage-3-large"] = m_stats
                current_config["usage_stats"] = usage_stats
                self.project.config = current_config
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(self.project, "config")
                self.db.commit()

            self.update_progress(100, status="ready")
            self.log(f"Segment vectors updated successfully. ({total_tokens} tokens)")
            
        except Exception as e:
            self.fail(e)
