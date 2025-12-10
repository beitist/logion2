from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Segment
from ..ai.engine import AITranslator

router = APIRouter(prefix="/translate", tags=["translate"])
translator = AITranslator()

@router.post("/segment/{segment_id}")
async def translate_single_segment(segment_id: str, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    # Perform Translation
    translated_text = translator.translate_segment(segment.source_content)
    
    # Update DB
    segment.target_content = translated_text
    segment.status = "translated"
    db.commit()
    
    return {"id": segment.id, "target_content": translated_text}

@router.post("/project/{project_id}")
async def translate_project(project_id: str, db: Session = Depends(get_db)):
    """
    Batch translate all draft segments.
    """
    segments = db.query(Segment).filter(
        Segment.project_id == project_id,
        Segment.status == "draft"
    ).all()
    
    count = 0
    for seg in segments:
        trans = translator.translate_segment(seg.source_content)
        seg.target_content = trans
        seg.status = "translated"
        count += 1
        
    db.commit()
    return {"translated_count": count}
