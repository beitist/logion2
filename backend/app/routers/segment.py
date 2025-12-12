from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Segment
from pydantic import BaseModel

class SegmentUpdate(BaseModel):
    target_content: str
    status: str | None = None

router = APIRouter(prefix="/segment", tags=["segment"])

@router.patch("/{segment_id}")
async def update_segment(segment_id: str, update: SegmentUpdate, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    segment.target_content = update.target_content
    # Update status if provided, otherwise default/keep? 
    # Frontend sends status.
    if update.status:
        segment.status = update.status
    else:
        # Fallback default if not provided (legacy)
        segment.status = "translated"  
    
    db.commit()
    db.refresh(segment)
    return segment
