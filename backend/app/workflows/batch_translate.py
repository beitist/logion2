import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment
from ..rag.manager import RAGManager
from ..database import SessionLocal
from .base import BaseWorkflow

from typing import List, Optional

def run_background_batch_translate(project_id: str, segment_ids: Optional[List[str]] = None):
    db = SessionLocal()
    try:
        wf = BatchTranslateWorkflow(db, project_id)
        wf.run(segment_ids)
    except Exception as e:
        print(f"Batch Translate Failed: {e}")
    finally:
        db.close()

class BatchTranslateWorkflow(BaseWorkflow):
    def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log(f"Starting Batch Translation...")
            
            # Fetch segments
            query = self.db.query(Segment).filter(Segment.project_id == self.project_id)
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))
                
            segments = query.all()
            if not segments:
                self.log("No segments found.")
                return
                
            segment_ids = [s.id for s in segments]
            self.log(f"Translating {len(segment_ids)} segments...")
            
            self.update_progress(0, status="processing")

            # Init Manager
            manager = RAGManager(self.project_id, self.db)
            
            try:
                results = asyncio.run(manager.generate_batch_draft(
                    segment_ids=segment_ids,
                    source_lang=self.project.source_lang,
                    target_lang=self.project.target_lang,
                    model_name=None, 
                    custom_prompt="Translate the following text accurately." 
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
                    # Update Target Content
                    seg.target_content = result.target_text
                    seg.status = "translated"
                    
                    # Also save as draft in metadata just in case
                    meta = seg.metadata_json or {}
                    meta['ai_draft'] = result.target_text

                    # Save Context Matches & Glossary
                    if result.context_used:
                        matches = result.context_used.matches or []
                        gloss = result.context_used.glossary_hits or []
                        serialized_ctx = [m.dict() for m in matches] + [m.dict() for m in gloss]
                        meta['context_matches'] = serialized_ctx

                    seg.metadata_json = dict(meta)
                    flag_modified(seg, "metadata_json")
                    
                    success_count += 1
                    
            self.db.commit()
            
            self.update_progress(100, status="ready")
            self.log(f"Batch Translation Complete. Updated {success_count} segments.")
            
        except Exception as e:
            self.fail(e)
