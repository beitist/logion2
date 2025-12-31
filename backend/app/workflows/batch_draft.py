import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment
from ..rag.manager import RAGManager
from ..database import SessionLocal
from .base import BaseWorkflow

# Use RAG logger? Or BaseWorkflow logger?
# BaseWorkflow uses "Workflow".
# We can use that.

from typing import List, Optional

def run_background_batch_draft(project_id: str, segment_ids: Optional[List[str]] = None):
    db = SessionLocal()
    try:
        wf = BatchDraftWorkflow(db, project_id)
        wf.run(segment_ids)
    except Exception as e:
        print(f"Batch Draft Failed: {e}")
    finally:
        db.close()

class BatchDraftWorkflow(BaseWorkflow):
    def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log(f"Starting Batch Draft Generation...")
            
            # Fetch segments
            query = self.db.query(Segment).filter(Segment.project_id == self.project_id)
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))
            
            segments = query.all()
            if not segments:
                self.log("No segments found.")
                return
                
            segment_ids = [s.id for s in segments]
            self.log(f"Generating drafts for {len(segment_ids)} segments...")
            
            self.update_progress(0, status="processing")

            # Init Manager
            manager = RAGManager(self.project_id, self.db)
            
            # Run Async Logic Synchronously
            try:
                # Assuming this script runs in a thread pool (BackgroundTasks), asyncio.run is safe/needed
                # provided there is no existing loop.
                # In FastAPI BackgroundTasks, it is a thread, so asyncio.run works.
                results = asyncio.run(manager.generate_batch_draft(
                    segment_ids=segment_ids,
                    source_lang=self.project.source_lang,
                    target_lang=self.project.target_lang,
                    model_name=None, 
                    custom_prompt="" 
                ))
            except Exception as e:
                self.fail(e)
                return

            success_count = 0
            for seg_id, result in results.items():
                if result.error:
                    continue
                    
                seg = next((s for s in segments if s.id == seg_id), None)
                if seg:
                    # Update Metadata
                    meta = seg.metadata_json or {}
                    meta['ai_draft'] = result.target_text
                    seg.metadata_json = dict(meta)
                    flag_modified(seg, "metadata_json")
                    success_count += 1
                    
            self.db.commit()
            
            self.update_progress(100, status="ready")
            self.log(f"Batch Draft Complete. Updated {success_count} segments.")
            
        except Exception as e:
            self.fail(e)
