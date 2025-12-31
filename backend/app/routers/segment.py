from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Segment
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel

class SegmentUpdate(BaseModel):
    target_content: str | None = None
    status: str | None = None
    metadata: dict | None = None

router = APIRouter(prefix="/segment", tags=["segment"])

@router.patch("/{segment_id}")
async def update_segment(segment_id: str, update: SegmentUpdate, db: Session = Depends(get_db)):
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
    
    # Return Dict without embedding
    res = segment.__dict__.copy()
    res.pop('embedding', None)
    res.pop('_sa_instance_state', None)
    return res
