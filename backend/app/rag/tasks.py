import logging
import asyncio
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Project, Segment, SegmentStatus
from .manager import RAGManager
from ..services.segment_service import SegmentService

logger = logging.getLogger("RAG.Tasks")

def generate_project_drafts(project_id: str):
    """
    Background Task: Generate drafts for all segments in a project.
    """
    db = SessionLocal()
    try:
        logger.info(f"Starting Batch Draft Generation for Project {project_id}...")
        
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.error(f"Project {project_id} not found.")
            return

        # Fetch all segments
        segments = db.query(Segment).filter(Segment.project_id == project_id).all()
        if not segments:
            logger.info("No segments found.")
            return
            
        segment_ids = [s.id for s in segments]
        logger.info(f"Generating drafts for {len(segment_ids)} segments...")
        
        # Init Manager
        manager = RAGManager(project_id, db)
        
        # Run Async Logic Synchronously
        # Since this runs in a ThreadPool (BackgroundTasks), we can use asyncio.run
        try:
            results = asyncio.run(manager.generate_batch_draft(
                segment_ids=segment_ids,
                source_lang=project.source_lang,
                target_lang=project.target_lang,
                model_name=None, # Use default
                custom_prompt="" # Or fetch from project config?
            ))
        except Exception as e:
            logger.error(f"Batch inference failed: {e}", exc_info=True)
            return

        # Save Results
        # We can use SegmentService logic or manual update
        # Manual is faster for batch
        
        success_count = 0
        for seg_id, result in results.items():
            if result.error:
                continue
                
            seg = next((s for s in segments if s.id == seg_id), None)
            if seg:
                # Update Metadata
                meta = seg.metadata_json or {}
                
                # Save Draft
                meta['ai_draft'] = result.target_text
                # Log context usage if needed
                
                seg.metadata_json = dict(meta)
                flag_modified(seg, "metadata_json")
                
                # If Auto-Translate project setting is explicitly ON, we might set target?
                # But typically this is "Draft Generation" so we just save draft.
                
                success_count += 1
                
        db.commit()
        logger.info(f"Batch Generation Complete. Updated {success_count} segments.")
        
    except Exception as e:
        logger.error(f"Fatal error in generate_project_drafts: {e}", exc_info=True)
    finally:
        db.close()

from sqlalchemy.orm.attributes import flag_modified
