from sqlalchemy.orm.attributes import flag_modified
from ..models import Segment
from ..rag.retrieval import RetrievalEngine
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

            engine = RetrievalEngine()
            count = 0

            self.update_progress(0, status="processing")

            for i, seg in enumerate(segments):
                # retrieve_matches returns (matches, usage_dict)
                matches, _usage = engine.retrieve_matches(
                    self.db, self.project_id, seg.source_content, limit=5, segment_id=seg.id
                )

                serialized = [m.model_dump() for m in matches]

                meta = seg.metadata_json or {}
                meta['cached_matches'] = serialized
                seg.metadata_json = dict(meta)
                flag_modified(seg, "metadata_json")

                count += 1
                if i % 10 == 0:
                    self.db.commit()  # Periodic commit

            self.db.commit()
            self.log(f"Preloaded matches for {count} segments.")
            self.update_progress(100, status="ready")

        except Exception as e:
            self.fail(e)
