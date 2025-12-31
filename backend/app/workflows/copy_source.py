from sqlalchemy.orm.attributes import flag_modified
from ..models import Segment
from .base import BaseWorkflow
from ..database import SessionLocal

def run_background_copy_source(project_id: str):
    db = SessionLocal()
    try:
        wf = CopySourceWorkflow(db, project_id)
        wf.run()
    except Exception as e:
        print(f"Copy Source Failed: {e}")
    finally:
        db.close()

class CopySourceWorkflow(BaseWorkflow):
    def run(self):
        try:
            self.log("Starting Copy Source to Target...")
            segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).all()
            
            count = 0
            for seg in segments:
                # Only if target is empty? Or overwrite?
                # User usually expects overwrite or "Fill empty".
                # "Copy Source to Target" usually implies overwrite.
                # But safer to check?
                # Let's overwrite but maybe respect status?
                # If status is "approved", maybe skip?
                # For now, explicit overwrite.
                
                seg.target_content = seg.source_content
                # detailed status logic: if it was empty, it's draft.
                if not seg.status or seg.status == "new":
                    seg.status = "draft"
                
                count += 1
            
            self.db.commit()
            self.log(f"Copied source to target for {count} segments.")
            self.update_progress(100, status="ready")
            
        except Exception as e:
            self.fail(e)
