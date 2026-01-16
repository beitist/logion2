"""
Workflow: Clear Draft Targets

Deletes all target content and AI drafts for segments that are NOT yet confirmed 
(status != 'translated'). Used when drafts were generated with wrong MT model.
"""
from ..models import Segment
from .base import BaseWorkflow
from ..database import SessionLocal
from sqlalchemy.orm.attributes import flag_modified


def run_background_clear_drafts(project_id: str):
    """Background Task Entrypoint."""
    db = SessionLocal()
    try:
        wf = ClearDraftsWorkflow(db, project_id)
        wf.run()
    except Exception as e:
        print(f"Clear Drafts Failed: {e}")
    finally:
        db.close()


class ClearDraftsWorkflow(BaseWorkflow):
    """
    Clears target content and AI drafts for unconfirmed segments.
    
    Criteria:
    - Only affects segments with status 'draft' or 'mt_draft'
    - Preserves segments with status 'translated' or 'approved'
    - Clears both target_content and metadata.ai_draft
    """
    
    def run(self):
        try:
            self.log("Starting Clear Draft Targets...")
            
            # Only clear segments that haven't been confirmed by user
            segments = self.db.query(Segment).filter(
                Segment.project_id == self.project_id,
                Segment.status.in_(['draft', 'mt_draft', 'error'])
            ).all()
            
            cleared_count = 0
            
            for seg in segments:
                # Clear target content
                if seg.target_content:
                    seg.target_content = None
                    cleared_count += 1
                
                # Clear AI draft from metadata
                if seg.metadata_json:
                    meta = dict(seg.metadata_json)
                    inner_meta = meta.get('metadata', {})
                    
                    # Remove AI-related fields
                    if 'ai_draft' in inner_meta:
                        del inner_meta['ai_draft']
                    if 'ai_model' in inner_meta:
                        del inner_meta['ai_model']
                    if 'ai_reasoning' in inner_meta:
                        del inner_meta['ai_reasoning']
                    if 'ai_alternatives' in inner_meta:
                        del inner_meta['ai_alternatives']
                    
                    meta['metadata'] = inner_meta
                    seg.metadata_json = meta
                    flag_modified(seg, 'metadata_json')
                
                # Reset status to draft
                seg.status = 'draft'
            
            self.db.commit()
            self.log(f"Cleared {cleared_count} draft targets. Reset {len(segments)} segments to 'draft' status.")
            self.update_progress(100, status="ready")
            
        except Exception as e:
            self.fail(e)
