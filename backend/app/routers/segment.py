from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..models import Segment, Project
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel
from ..services.auto_glossary import AutoGlossaryService, hash_content

class SegmentUpdate(BaseModel):
    target_content: str | None = None
    status: str | None = None
    metadata: dict | None = None

router = APIRouter(prefix="/segment", tags=["segment"])

@router.patch("/{segment_id}")
async def update_segment(segment_id: str, update: SegmentUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    if update.target_content is not None:
        segment.target_content = update.target_content

    # Update metadata if provided (Merge)
    if update.metadata:
        current_meta = dict(segment.metadata_json or {})
        # We explicitly update the 'metadata' sub-dictionary or top-level?
        # Plan says: metadata_json['metadata']['flagged']
        # Frontend sends { metadata: { flagged: true } }
        # So we merge `update.metadata` into `current_meta['metadata']`?
        # Or we just assume `update.metadata` IS the `metadata` key content?
        # Let's assume the frontend sends the whole "metadata" (location info + flags) or partial updates to it.
        # Safest is to merge keys.
        
        # Ensure 'metadata' key exists
        if "metadata" not in current_meta:
            current_meta["metadata"] = {}
            
        # Update keys provided
        current_meta["metadata"].update(update.metadata)
        
        segment.metadata_json = current_meta
        flag_modified(segment, "metadata_json")

    # Update status if provided
    if update.status:
        segment.status = update.status
    elif update.target_content is not None and not update.status:
        # Fallback default if content changed but status not provided
        # Only if we actually touched content
        segment.status = "translated" 
    
    db.commit()
    db.refresh(segment)

    # Auto-glossary re-extraction: only if this segment already had auto-glossary
    # AND the target content actually changed (hash differs)
    if update.target_content is not None:
        meta = segment.metadata_json or {}
        inner_meta = meta.get("metadata", {})
        old_hash = inner_meta.get("auto_glossary_hash")
        if old_hash and hash_content(update.target_content) != old_hash:
            background_tasks.add_task(
                _trigger_auto_glossary_re_extract,
                segment.id,
                segment.project_id,
            )

    # Return Dict without embedding
    res = segment.__dict__.copy()
    res.pop('embedding', None)
    res.pop('_sa_instance_state', None)
    return res


async def _trigger_auto_glossary_re_extract(segment_id: str, project_id: str):
    """Background task: re-extract auto-glossary after user edits a segment."""
    db = SessionLocal()
    try:
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        project = db.query(Project).filter(Project.id == project_id).first()
        if not segment or not project or not segment.target_content:
            return

        config = project.config or {}
        ai_settings = config.get("ai_settings", {})
        topic = ai_settings.get("topic_description", "")
        model_name = ai_settings.get("workflow_model") or ai_settings.get("model")

        service = AutoGlossaryService(project_id, db)
        await service.extract_and_store(
            segment_id=segment.id,
            source_text=segment.source_content,
            target_text=segment.target_content,
            topic=topic,
            source_lang=project.source_lang,
            target_lang=project.target_lang,
            model_name=model_name,
        )

        # Update hash
        meta = dict(segment.metadata_json or {})
        if "metadata" not in meta:
            meta["metadata"] = {}
        meta["metadata"]["auto_glossary_hash"] = hash_content(segment.target_content)
        segment.metadata_json = meta
        flag_modified(segment, "metadata_json")
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger("AutoGlossary").error(f"Re-extract failed: {e}")
    finally:
        db.close()
