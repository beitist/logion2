import asyncio
from sqlalchemy.orm.attributes import flag_modified
from ..models import Segment
from ..rag.manager import RAGManager
from .base import BaseWorkflow
from ..database import SessionLocal

def run_background_preload_matches(project_id: str):
    db = SessionLocal()
    try:
        wf = PreloadMatchesWorkflow(db, project_id)
        wf.run()
    except Exception as e:
        print(f"Preload Matches Failed: {e}")
    finally:
        db.close()

class PreloadMatchesWorkflow(BaseWorkflow):
    def run(self):
        try:
            self.log("Starting Preload Matches...")
            segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).all()
            
            manager = RAGManager(self.project_id, self.db)
            count = 0
            
            # This might be slow if serial.
            # But retrieval is vectorized/fast.
            # We can batch it if manager supports batch retrieval?
            # manager.retrieve is per segment.
            
            self.update_progress(0, status="processing")
            
            for i, seg in enumerate(segments):
                # We want matches, not draft.
                # Manager doesn't expose public `retrieve` nicely? 
                # It has `context = await self.retrieve_context(segment)`.
                # Let's use internal method or add public one?
                # accessing _retrieve_context is okay-ish within module but `manager` is in another package.
                # Let's see RAGManager public API.
                
                # Assuming internal access for now to solve the task.
                # Or re-implement retrieval call using RetrievalEngine directly?
                # RAGManager encapsulates the complexity (query expansion etc).
                # But `retrieve_context` is the key.
                
                # We need asyncio.run if sync.
                # If we are in thread, we can run loop for each? Or one loop?
                pass
                
            # Better approach: Use RetrievalEngine directly to get matches.
            # Accessing `manager.engine`.
            from ..rag.retrieval import RetrievalEngine
            engine = RetrievalEngine()
            
            for i, seg in enumerate(segments):
                 matches = engine.retrieve_matches(self.db, self.project_id, seg.source_content, limit=5, segment_id=seg.id)
                 
                 # Serialize matches
                 # TranslationMatch object needs to be dict
                 serialized = [m.dict() for m in matches]
                 
                 meta = seg.metadata_json or {}
                 meta['cached_matches'] = serialized
                 seg.metadata_json = dict(meta)
                 flag_modified(seg, "metadata_json")
                 
                 count += 1
                 if i % 10 == 0:
                     self.db.commit() # Periodic commit
                     
            self.db.commit()
            self.log(f"Preloaded matches for {count} segments.")
            self.update_progress(100, status="ready")

        except Exception as e:
            self.fail(e)
