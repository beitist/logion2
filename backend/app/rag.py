import os
import google.generativeai as genai
from sqlalchemy.orm import Session
from .models import Project, ProjectFile, ContextChunk, ProjectFileCategory
from .storage import download_file
from dotenv import load_dotenv
import zipfile
import re
from xml.etree import ElementTree

load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def extract_text_from_docx(docx_path):
    try:
        text_content = []
        with zipfile.ZipFile(docx_path) as z:
            xml_content = z.read("word/document.xml")
            tree = ElementTree.fromstring(xml_content)
            NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for p in tree.iter(f"{NS}p"):
                texts = [node.text for node in p.iter(f"{NS}t") if node.text]
                if texts:
                    text_content.append("".join(texts))
        return "\n".join(text_content)
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    if not text:
        return chunks
        
    start = 0
    text_len = len(text)
    
    CHAR_CHUNK = chunk_size * 4 
    CHAR_OVERLAP = overlap * 4
    
    while start < text_len:
        end = min(start + CHAR_CHUNK, text_len)
        chunk = text[start:end]
        
        if end < text_len:
            last_period = chunk.rfind('.')
            if last_period > CHAR_CHUNK * 0.5:
                end = start + last_period + 1
                chunk = text[start:end]
            
        chunks.append(chunk)

        if end >= text_len:
            break
            
        step = end - CHAR_OVERLAP
        if step <= start:
             start = start + 1
        else:
             start = step
        
    return chunks

from .database import SessionLocal

def reingest_project(project_id: str):
    """
    Clears existing RAG vectors and re-runs ingestion.
    """
    db = SessionLocal()
    try:
        # 1. Clear existing chunks
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return
            
        # Delete chunks for this project's files
        # Find all file IDs
        file_ids = db.query(ProjectFile.id).filter(ProjectFile.project_id == project_id).all()
        file_ids = [f[0] for f in file_ids]
        
        if file_ids:
            db.query(ContextChunk).filter(ContextChunk.file_id.in_(file_ids)).delete(synchronize_session=False)
            db.commit()
            
        # 2. Reset log
        project.ingestion_logs = []
        project.rag_status = "created"
        db.commit()
        db.close()
        
        # 3. Call Ingest
        ingest_project_files(project_id)
        
    except Exception as e:
        print(f"Re-Ingest Error: {e}")

def ingest_project_files(project_id: str):
    """
    Task to be run in background.
    """
    db = SessionLocal()
    
    def log_msg(msg: str):
        print(msg)
        try:
             p = db.query(Project).filter(Project.id == project_id).first()
             current_logs = list(p.ingestion_logs) if p.ingestion_logs else []
             from datetime import datetime
             current_logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
             p.ingestion_logs = current_logs
             db.commit()
        except Exception as e:
             print(f"Log error: {e}")

    try:
        log_msg(f"Starting analysis for project {project_id}")
        
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return

        project.rag_status = "ingesting"
        db.commit()
    
        # Determine strict defaults
        categories_to_ingest = [ProjectFileCategory.legal.value, ProjectFileCategory.background.value]
        
        # Check Project Config for 'include_source_rag'
        # Default: True? Plan said Internal Fuzzy Match is useful.
        # But let's check config if present, or existing setting.
        # Assuming user defaulted to Yes for now based on prompt.
        categories_to_ingest.append(ProjectFileCategory.source.value)
        
        target_files = db.query(ProjectFile).filter(
            ProjectFile.project_id == project_id,
            ProjectFile.category.in_(categories_to_ingest)
        ).all()
        
        log_msg(f"Found {len(target_files)} files to process (Source/Legal/Background).")

        total_chunks = 0
        BATCH_SIZE = 100
        
        for file_record in target_files:
            log_msg(f"Processing file: {file_record.filename} ({file_record.category})...")
            
            # 1. Download
            temp_path = f"temp_rag_{file_record.id}_{file_record.filename}"
            try:
                download_file(file_record.file_path, temp_path)
                
                # 2. Extract
                if file_record.filename.endswith(".docx"):
                    raw_text = extract_text_from_docx(temp_path)
                elif file_record.filename.endswith(".xlsx"):
                    # TODO: Implement XLSX support if needed
                    raw_text = ""
                else: 
                    # Try text? 
                    raw_text = ""
                    
                if not raw_text:
                    log_msg(f"Skipping {file_record.filename} (empty or unsupported format)")
                    continue
                
                log_msg(f"Extracted {len(raw_text)} chars. Cleaning & Chunking...")
                text = clean_text(raw_text)
                
                # 3. Chunk
                chunks = chunk_text(text)
                log_msg(f"Generated {len(chunks)} chunks. Vektorizing...")
                
                # 4. Embed & Store in batches
                for i in range(0, len(chunks), BATCH_SIZE):
                    batch = chunks[i : i + BATCH_SIZE]
                    # log_msg(f"Embedding batch {i}...")
                    
                    try:
                        result = genai.embed_content(
                            model='models/gemini-embedding-001',
                            content=batch,
                            task_type="retrieval_document",
                            title=file_record.filename,
                            output_dimensionality=1536
                        )
                        
                        embeddings = result['embedding']
                        
                        db_chunks = []
                        for content, vector in zip(batch, embeddings):
                            db_chunks.append(ContextChunk(
                                file_id=file_record.id,
                                content=content,
                                embedding=vector
                            ))
                        
                        db.add_all(db_chunks)
                        db.commit() 
                        total_chunks += len(batch)
                        log_msg(f"Stored batch {i // BATCH_SIZE + 1} ({len(batch)} vectors).")
                        
                    except Exception as api_err:
                        log_msg(f"GOOGLE API ERROR: {str(api_err)}")
                        # Don't crash entire process, try next batch?
                        continue

            except Exception as e:
                log_msg(f"ERROR processing {file_record.filename}: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        project.rag_status = "ready"
        log_msg(f"RAG READY. Knowledge base refreshed: {total_chunks} vectors.")
        
        # Trigger Draft Generation for Segments
        log_msg("Starting automatic draft generation for segments...")
        generate_project_drafts(project_id)
        log_msg("Draft generation complete.")
        
        db.commit()

    except Exception as e:
        log_msg(f"FATAL ERROR: {e}")
        try:
             project.rag_status = "error"
             db.commit()
        except:
             pass
    finally:
        db.close()

# --- Search Logic ---

def search_context_for_segment(segment_text: str, project_id: str, db: Session, limit=5, threshold=0.4):
    """
    Retrieves chunks relevant to the segment.
    Filters by similarity (1 - cosine_distance).
    0.0 = no similarity, 1.0 = identical.
    Wait: pgvector cosine_distance is 0 for identical, 1 for opposite?
    pgvector: <=> operator is Cosine Distance. (1 - Cosine Similarity).
    So if user wants threshold 0.8 Similarity, that means Distance < 0.2.
    """
    if not segment_text or len(segment_text) < 5:
        return []

    # 1. Embed Query
    try:
        query_vector = genai.embed_content(
            model='models/gemini-embedding-001',
            content=segment_text,
            task_type="retrieval_query",
            output_dimensionality=1536
        )['embedding']
    except Exception as e:
        print(f"Embedding error: {e}")
        return []
        
    # Convert 'Similarity Threshold' (0.0-1.0) to 'Distance Limit' (0.0-2.0)
    # Higher similarity = Lower distance.
    # threshold 0.8 means distance must be < 0.2
    distance_limit = 1.0 - threshold
    
    # 2. Search
    results = db.query(ContextChunk, ProjectFile).join(ProjectFile)\
        .filter(ProjectFile.project_id == project_id)\
        .filter(ContextChunk.embedding.cosine_distance(query_vector) < distance_limit)\
        .order_by(ContextChunk.embedding.cosine_distance(query_vector))\
        .limit(limit)\
        .all()
        
    structured_results = []
    for chunk, file in results:
        # Determine strictness based on category
        match_type = "mandatory" if file.category == "legal" else \
                     "internal" if file.category == "source" else "optional"
        
        structured_results.append({
            "id": chunk.id,
            "content": chunk.content,
            "filename": file.filename,
            "type": match_type,
            "category": file.category
        })
        
    return structured_results

def generate_segment_draft(segment_text: str, source_lang: str, target_lang: str, project_id: str, db: Session, threshold=0.4, model_name="gemini-2.0-flash"):
    """
    Generates a draft translation using RAG context.
    Returns { target_text: str, context_matches: list }
    """
    
    # 1. Retrieve Context
    matches = search_context_for_segment(segment_text, project_id, db, threshold=threshold)
    
    # 2. Construct Prompt
    mandatory_context = "\n".join([f"- {m['content']} (Source: {m['filename']})" for m in matches if m['type'] == 'mandatory'])
    internal_context = "\n".join([f"- {m['content']} (Source: {m['filename']})" for m in matches if m['type'] == 'internal']) # Source file self-matches
    optional_context = "\n".join([f"- {m['content']} (Source: {m['filename']})" for m in matches if m['type'] == 'optional'])
    
    prompt = f"""
    You are a professional translator for technical and development cooperation texts.
    Translate the following text from {source_lang} to {target_lang}.
    
    Input Text: "{segment_text}"
    
    Instructions:
    - Maintain the tone and style of the input.
    - PREFER terminology found in the MANDATORY REFERENCES below.
    - Check INTERNAL CONSISTENCY with other source segments if provided.
    - Use OPTIONAL REFERENCES for style/context inspiration.
    - Return ONLY the translated text, no explanations.
    - Preserve XML tags like <1>...</1> exactly if present.
    
    """
    
    if mandatory_context:
        prompt += f"\nMANDATORY REFERENCES (Must follow terminology):\n{mandatory_context}\n"
        
    if internal_context:
        prompt += f"\nINTERNAL CONTEXT (Previous/Similar source segments):\n{internal_context}\n"

    if optional_context:
        prompt += f"\nOPTIONAL REFERENCES (Context/Inspiration):\n{optional_context}\n"
        
    # 3. Call Gemini
    try:
        # model_name passed from caller (config)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        draft = response.text.strip()
    except Exception as e:
        print(f"Generation error: {e}")
        draft = "" 
        
    return {
        "target_text": draft,
        "context_matches": matches
    }

def generate_project_drafts(project_id: str):
    """
    Background task: Generates drafts and context matches for all segments in a project.
    """
    from .database import SessionLocal
    from .models import Segment, Project
    
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project: return
        
        segments = db.query(Segment).filter(Segment.project_id == project_id, Segment.target_content == None).all()
        
        # Determine config
        config = project.config or {}
        ai_settings = config.get("ai_settings", {})
        threshold = float(ai_settings.get("similarity_threshold", 0.4))
        # Default to 2.0-flash if not set
        model = ai_settings.get("model", "gemini-2.0-flash")
        
        print(f"Generating drafts for project {project_id} ({len(segments)} segments)...")
        
        # We can parallelize or batch? For now sequential.
        for seg in segments:
            try:
                res = generate_segment_draft(
                    segment_text=seg.source_content,
                    source_lang=project.source_lang,
                    target_lang=project.target_lang,
                    project_id=project_id,
                    db=db,
                    threshold=threshold,
                    model_name=model
                )
                
                seg.target_content = res["target_text"]
                current_meta = seg.metadata_json or {}
                current_meta['context_matches'] = res['context_matches']
                seg.metadata_json = current_meta
                # seg.status = 'draft' 
            except Exception as se:
                print(f"Error seg {seg.id}: {se}")
        
        db.commit()
        print(f"Draft generation complete for {project_id}.")
        
    except Exception as e:
        print(f"Error generating drafts: {e}")
    finally:
        db.close()
