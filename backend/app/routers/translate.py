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
    
    project = db.query(Project).filter(Project.id == segment.project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    # 1. Fetch Context (Previous 10)
    prev_segments = db.query(Segment).filter(
        Segment.project_id == segment.project_id,
        Segment.index < segment.index,
        Segment.index >= segment.index - 10
    ).order_by(Segment.index.asc()).all()
    
    # 2. Fetch Context (Next 3)
    next_segments = db.query(Segment).filter(
        Segment.project_id == segment.project_id,
        Segment.index > segment.index,
        Segment.index <= segment.index + 3
    ).order_by(Segment.index.asc()).all()
    
    # Format for AI
    prev_ctx = [{"index": s.index, "source": s.source_content, "target": s.target_content} for s in prev_segments]
    next_ctx = [{"index": s.index, "source": s.source_content} for s in next_segments]
    
    # 3. Perform Translation
    # Project Config might act as project_config
    result = translator.translate_segment(
        current_text=segment.source_content,
        project_config=project.config,
        prev_context=prev_ctx,
        next_context=next_ctx
    )
    
    # Handle Structured Response or Fallback
    if isinstance(result, dict):
        translated_text = result.get("translation_text", "")
        reasoning = result.get("reasoning", "")
        # Store reasoning in metadata
        meta = segment.metadata_json or {}
        meta["ai_reasoning"] = reasoning
        meta["ai_alternatives"] = result.get("alternatives", [])
        segment.metadata_json = meta
    else:
        # Fallback string
        translated_text = str(result)
    
    # Update DB
    segment.target_content = translated_text
    segment.status = "translated"
    db.commit()
    
    return {"id": segment.id, "target_content": translated_text}

@router.post("/project/{project_id}")
async def translate_project(project_id: str, db: Session = Depends(get_db)):
    """
    Batch translate all draft segments sequentially to maintain context flow.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    # Fetch ALL segments (to build context in-memory efficiently)
    all_segments = db.query(Segment).filter(
        Segment.project_id == project_id
    ).order_by(Segment.index.asc()).all()
    
    count = 0
    
    # Iterate
    # We use a lookup list/map to easily grab slices
    # But since all_segments is sorted, we can use list slicing if indices match position.
    # Safe approach: List is ordered.
    
    for i, seg in enumerate(all_segments):
        if seg.status != "draft":
            continue
            
        # Build Context from memory list (which contains updated translations from this loop!)
        # Prev: up to 10 before i
        start = max(0, i - 10)
        prev_slice = all_segments[start:i]
        
        # Next: up to 3 after i
        end = min(len(all_segments), i + 4) # i+1 to i+4
        next_slice = all_segments[i+1:end]
        
        prev_ctx = [{"index": s.index, "source": s.source_content, "target": s.target_content} for s in prev_slice]
        next_ctx = [{"index": s.index, "source": s.source_content} for s in next_slice]
        
        result = translator.translate_segment(
            current_text=seg.source_content,
            project_config=project.config,
            prev_context=prev_ctx,
            next_context=next_ctx
        )
        
        if isinstance(result, dict):
            trans = result.get("translation_text", "")
            reasoning = result.get("reasoning", "")
            meta = seg.metadata_json or {}
            meta["ai_reasoning"] = reasoning
            seg.metadata_json = meta
        else:
            trans = str(result)

        seg.target_content = trans
        seg.status = "translated"
        count += 1
        
        # Periodic commit? Or One Big Commit?
        # For user experience (stream), one big commit might timeout if huge.
        # But for 4M context / flow, we want atomicity or checkpointing.
        # Let's commit every 10 to be safe? 
        if count % 10 == 0:
             db.commit()

    db.commit()
    return {"translated_count": count}
