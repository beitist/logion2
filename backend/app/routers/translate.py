from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Segment, Project
from ..ai.engine import AITranslator

router = APIRouter(prefix="/translate", tags=["translate"])
translator = AITranslator()

from ..glossary_service import GlossaryMatcher

@router.post("/segment/{segment_id}")
async def translate_single_segment(segment_id: str, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    project = db.query(Project).filter(Project.id == segment.project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    # Fetch Context (Previous 10 / Next 3)
    prev_segments = db.query(Segment).filter(
        Segment.project_id == segment.project_id,
        Segment.index < segment.index,
        Segment.index >= segment.index - 10
    ).order_by(Segment.index.asc()).all()
    
    next_segments = db.query(Segment).filter(
        Segment.project_id == segment.project_id,
        Segment.index > segment.index,
        Segment.index <= segment.index + 3
    ).order_by(Segment.index.asc()).all()
    
    prev_ctx = [{"index": s.index, "source": s.source_content, "target": s.target_content} for s in prev_segments]
    next_ctx = [{"index": s.index, "source": s.source_content} for s in next_segments]
    
    # [NEW] Glossary Matching
    matcher = GlossaryMatcher(project.id, db)
    glossary_hits = matcher.find_matches(segment.source_content)
    
    # Perform Translation
    result = translator.translate_segment(
        current_text=segment.source_content,
        project_config=project.config,
        prev_context=prev_ctx,
        next_context=next_ctx,
        glossary_matches=glossary_hits
    )
    
    # Handle Response
    if isinstance(result, dict):
        translated_text = result.get("translation_text", "")
        reasoning = result.get("reasoning", "")
        meta = segment.metadata_json or {}
        meta["ai_reasoning"] = reasoning
        meta["ai_alternatives"] = result.get("alternatives", [])
        segment.metadata_json = meta
    else:
        translated_text = str(result)
    
    segment.target_content = translated_text
    segment.status = "translated"
    db.commit()
    
    return {"id": segment.id, "target_content": translated_text}

@router.post("/project/{project_id}")
async def translate_project(project_id: str, db: Session = Depends(get_db)):
    """
    Batch translate.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    all_segments = db.query(Segment).filter(
        Segment.project_id == project_id
    ).order_by(Segment.index.asc()).all()
    
    # [NEW] Pre-load Glossary Matcher (Avoid reload per segment)
    matcher = GlossaryMatcher(project_id, db)
    
    count = 0
    for i, seg in enumerate(all_segments):
        if seg.status != "draft":
            continue
            
        start = max(0, i - 10)
        prev_slice = all_segments[start:i]
        end = min(len(all_segments), i + 4)
        next_slice = all_segments[i+1:end]
        
        prev_ctx = [{"index": s.index, "source": s.source_content, "target": s.target_content} for s in prev_slice]
        next_ctx = [{"index": s.index, "source": s.source_content} for s in next_slice]
        
        # [NEW] Glossary
        glossary_hits = matcher.find_matches(seg.source_content)
        
        result = translator.translate_segment(
            current_text=seg.source_content,
            project_config=project.config,
            prev_context=prev_ctx,
            next_context=next_ctx,
            glossary_matches=glossary_hits
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
        
        if count % 10 == 0:
             db.commit()

    db.commit()
    return {"translated_count": count}
