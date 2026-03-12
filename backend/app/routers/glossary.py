
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import GlossaryEntry, Project
from ..glossary_service import GlossaryMatcher, invalidate_glossary_cache
from pydantic import BaseModel
import csv
import io

router = APIRouter(prefix="/project/{project_id}/glossary", tags=["glossary"])

class GlossaryAddRequest(BaseModel):
    source_term: str
    target_term: str
    context_note: str = None

class GlossaryUpdateRequest(BaseModel):
    source_term: str = None
    target_term: str = None
    context_note: str = None

@router.post("")
def add_glossary_term(project_id: str, item: GlossaryAddRequest, db: Session = Depends(get_db)):
    from ..glossary_service import get_nlp
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
         raise HTTPException(status_code=404, detail="Project not found")

    # Add directly to DB — avoid building the full GlossaryMatcher (slow with many entries)
    nlp = get_nlp()
    doc = nlp(item.source_term.strip())
    lemma = " ".join([t.lemma_ for t in doc])

    entry = GlossaryEntry(
        project_id=project_id,
        source_term=item.source_term.strip(),
        target_term=item.target_term.strip(),
        source_lemma=lemma,
        context_note=item.context_note,
        origin="manual",
    )
    db.add(entry)
    db.commit()
    invalidate_glossary_cache(project_id)

    return {"id": entry.id, "source": entry.source_term, "lemma": entry.source_lemma}

@router.get("")
def list_glossary(project_id: str, db: Session = Depends(get_db)):
    entries = db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).order_by(GlossaryEntry.source_term).all()
    return [{
        "id": e.id,
        "source": e.source_term,
        "target": e.target_term,
        "lemma": e.source_lemma,
        "note": e.context_note,
        "origin": getattr(e, "origin", "manual"),
        "segment_id": getattr(e, "segment_id", None),
    } for e in entries]
    
@router.put("/{entry_id}")
def update_glossary_term(project_id: str, entry_id: str, item: GlossaryUpdateRequest, db: Session = Depends(get_db)):
    from ..glossary_service import get_nlp
    entry = db.query(GlossaryEntry).filter(
        GlossaryEntry.id == entry_id,
        GlossaryEntry.project_id == project_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Glossary entry not found")

    nlp = get_nlp()

    if item.source_term is not None:
        entry.source_term = item.source_term.strip()
        doc = nlp(entry.source_term)
        entry.source_lemma = " ".join([t.lemma_ for t in doc])
    if item.target_term is not None:
        entry.target_term = item.target_term.strip()
    if item.context_note is not None:
        entry.context_note = item.context_note.strip() or None

    db.commit()
    db.refresh(entry)
    invalidate_glossary_cache(project_id)

    return {
        "id": entry.id,
        "source": entry.source_term,
        "target": entry.target_term,
        "lemma": entry.source_lemma,
        "note": entry.context_note
    }

@router.delete("/{entry_id}")
def delete_glossary_term(project_id: str, entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(GlossaryEntry).filter(
        GlossaryEntry.id == entry_id,
        GlossaryEntry.project_id == project_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Glossary entry not found")

    db.delete(entry)
    db.commit()
    invalidate_glossary_cache(project_id)
    return {"deleted": entry_id}

@router.post("/upload")
async def upload_glossary(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    decoded = content.decode('utf-8-sig') # Handle BOM automatically
    
    # Detect delimiter: count occurrences in first line (header)
    first_line = decoded.split('\n', 1)[0]
    counts = {d: first_line.count(d) for d in ['\t', ';', ',']}
    delimiter = max(counts, key=counts.get) if any(counts.values()) else ','
        
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
    
    # Normalize headers to lowercase to handle Source/source
    # DictReader reads headers from first line.
    # We can inspect fieldnames.
    fieldnames = [f.lower().strip() for f in reader.fieldnames or []]
    
    # Mapping for case-insensitive lookup
    # But DictReader rows use original keys.
    # We need to normalize row keys or just try variations.
    
    from ..glossary_service import get_nlp
    nlp = get_nlp()
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
            src = src.strip()
            tgt = tgt.strip()
            doc = nlp(src)
            lemma = " ".join([t.lemma_ for t in doc])
            entry = GlossaryEntry(
                project_id=project_id,
                source_term=src,
                target_term=tgt,
                source_lemma=lemma,
                context_note=note.strip() if note else None,
                origin="manual",
            )
            db.add(entry)
            count += 1

    db.commit()
    invalidate_glossary_cache(project_id)
    return {"added": count}
