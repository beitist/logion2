
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import GlossaryEntry, Project
from ..glossary_service import GlossaryMatcher
from pydantic import BaseModel
import csv
import io

router = APIRouter(prefix="/project/{project_id}/glossary", tags=["glossary"])

class GlossaryAddRequest(BaseModel):
    source_term: str
    target_term: str
    context_note: str = None

@router.post("")
def add_glossary_term(project_id: str, item: GlossaryAddRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    matcher = GlossaryMatcher(project_id, db)
    entry = matcher.add_term(item.source_term, item.target_term, item.context_note)
    
    return {"id": entry.id, "source": entry.source_term, "lemma": entry.source_lemma}

@router.get("")
def list_glossary(project_id: str, db: Session = Depends(get_db)):
    entries = db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).all()
    return [{
        "id": e.id,
        "source": e.source_term,
        "target": e.target_term,
        "lemma": e.source_lemma,
        "note": e.context_note
    } for e in entries]
    
@router.post("/upload")
async def upload_glossary(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    decoded = content.decode('utf-8-sig') # Handle BOM automatically
    
    # content is bytes, decoded is str
    # Use sniff to find delimiter
    try:
        # Sniff the first few lines
        sample = decoded[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=[',', ';', '\t'])
        delimiter = dialect.delimiter
    except Exception as e:
        print(f"CSV Sniff failed, defaulting to comma: {e}")
        delimiter = ','
        
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
    
    # Normalize headers to lowercase to handle Source/source
    # DictReader reads headers from first line.
    # We can inspect fieldnames.
    fieldnames = [f.lower().strip() for f in reader.fieldnames or []]
    
    # Mapping for case-insensitive lookup
    # But DictReader rows use original keys.
    # We need to normalize row keys or just try variations.
    
    matcher = GlossaryMatcher(project_id, db)
    count = 0
    
    for row in reader:
        # Robust access
        src = None
        tgt = None
        note = None
        
        for k, v in row.items():
            if not k: continue
            k_lower = k.lower().strip()
            
            # Source variations
            if k_lower in ['source', 'source_term', 'term', 'original', 'lemma', 'de', 'deutsch', 'german']: 
                src = v
            # Target variations
            elif k_lower in ['target', 'target_term', 'translation', 'en', 'english', 'englisch']: 
                tgt = v
            # Note variations
            elif k_lower in ['note', 'notes', 'comment', 'comments', 'context', 'description']: 
                note = v
            
        if src and tgt:
            matcher.add_term(src, tgt, note)
            count += 1
            
    return {"added": count}
