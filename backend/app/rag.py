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

# Helper for basic docx text extraction (simplified, no need for full parser overhead for RAG)
def extract_text_from_docx(docx_path):
    try:
        text_content = []
        with zipfile.ZipFile(docx_path) as z:
            xml_content = z.read("word/document.xml")
            tree = ElementTree.fromstring(xml_content)
            # Namespace map usually needed
            NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            
            # Iterate paragraphs
            for p in tree.iter(f"{NS}p"):
                texts = [node.text for node in p.iter(f"{NS}t") if node.text]
                if texts:
                    text_content.append("".join(texts))
        return "\n".join(text_content)
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""

def clean_text(text):
    # Remove excessive whitespace
    return re.sub(r'\s+', ' ', text).strip()

def chunk_text(text, chunk_size=500, overlap=50):
    """
    Simple sliding window chunker.
    Ideally we'd split by sentences, but for now fixed char/token count approx.
    Using characters for simplicity (approx 4 chars/token).
    """
    chunks = []
    if not text:
        return chunks
        
    start = 0
    text_len = len(text)
    
    # Approx 2000 chars ~ 500 tokens
    CHAR_CHUNK = chunk_size * 4 
    CHAR_OVERLAP = overlap * 4
    
    while start < text_len:
        end = min(start + CHAR_CHUNK, text_len)
        chunk = text[start:end]
        
        # Try to break at a period or newline to be cleaner
        last_period = chunk.rfind('.')
        if last_period > CHAR_CHUNK * 0.5: # Only if period is in second half
            end = start + last_period + 1
            chunk = text[start:end]
            
        chunks.append(chunk)
        start = end - CHAR_OVERLAP 
        
    return chunks

from .database import SessionLocal

def ingest_project_files(project_id: str):
    """
    Task to be run in background.
    1. Fetch all 'legal' and 'background' files for the project.
    2. Extract text -> Chunk -> Embed -> Store.
    3. Update Project rag_status.
    """
    db = SessionLocal()
    
    def log_msg(msg: str):
        print(msg)
        try:
             # Refresh log list and append
             # Note: Postgres JSON append is tricky with SQLAlchemy if not using specific ops.
             # Easiest: read, append, write. (Race condition possible but unlikely for single writer)
             p = db.query(Project).filter(Project.id == project_id).first()
             current_logs = list(p.ingestion_logs) if p.ingestion_logs else []
             current_logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
             p.ingestion_logs = current_logs
             db.commit()
        except Exception as e:
             print(f"Log error: {e}")

    from datetime import datetime
    
    try:
        log_msg(f"Starting analysis for project {project_id}")
        
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            print(f"Project {project_id} not found")
            return

        project.rag_status = "ingesting"
        db.commit()
    
        # Get files that are NOT source
        target_files = db.query(ProjectFile).filter(
            ProjectFile.project_id == project_id,
            ProjectFile.category.in_([ProjectFileCategory.legal.value, ProjectFileCategory.background.value])
        ).all()
        
        log_msg(f"Found {len(target_files)} reference files to process.")

        total_chunks = 0
        BATCH_SIZE = 100
        
        for file_record in target_files:
            log_msg(f"Processing file: {file_record.filename}...")
            
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
                    
                    # Google Embed Call
                    result = genai.embed_content(
                        model='models/text-embedding-004',
                        content=batch,
                        task_type="retrieval_document",
                        title=file_record.filename
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
                    log_msg(f"Embedded batch {i // BATCH_SIZE + 1} ({len(batch)} vectors stored).")

            except Exception as e:
                log_msg(f"ERROR processing {file_record.filename}: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        project.rag_status = "ready"
        log_msg(f"RAG READY. Total knowledge base: {total_chunks} vectors.")
        db.commit()

    except Exception as e:
        log_msg(f"FATAL ERROR: {e}")
        try:
             project.rag_status = "error"
             db.commit()
        except:
             pass

    except Exception as e:
        print(f"Fatal RAG error: {e}")
        try:
             project.rag_status = "error"
             db.commit()
        except:
             pass
    finally:
        db.close()

# --- Search Logic ---

def search_context_for_segment(segment_text: str, project_id: str, db: Session, limit=3):
    """
    Retrieves chunks relevant to the segment.
    """
    if not segment_text or len(segment_text) < 5:
        return []

    # 1. Embed Query
    try:
        query_vector = genai.embed_content(
            model='models/text-embedding-004',
            content=segment_text,
            task_type="retrieval_query"
        )['embedding']
    except Exception as e:
        print(f"Embedding error: {e}")
        return []
    
    # 2. Search
    results = db.query(ContextChunk, ProjectFile).join(ProjectFile)\
        .filter(ProjectFile.project_id == project_id)\
        .order_by(ContextChunk.embedding.cosine_distance(query_vector))\
        .limit(limit)\
        .all()
        
    structured_results = []
    for chunk, file in results:
        # Determine strictness based on category
        match_type = "mandatory" if file.category == "legal" else "optional"
        
        structured_results.append({
            "id": chunk.id,
            "content": chunk.content,
            "filename": file.filename,
            "type": match_type,
            "category": file.category
        })
        
    return structured_results

def generate_segment_draft(segment_text: str, source_lang: str, target_lang: str, project_id: str, db: Session):
    """
    Generates a draft translation using RAG context.
    Returns { target_text: str, context_matches: list }
    """
    
    # 1. Retrieve Context
    matches = search_context_for_segment(segment_text, project_id, db)
    
    # 2. Construct Prompt
    # We want to force usage of mandatory terms if applicable.
    # Since we retrieve CHUNKS (paragraphs), we don't have exact term-to-term maps unless we extracted them.
    # We pass the chunks as "Reference Material".
    
    mandatory_context = "\n".join([f"- {m['content']} (Source: {m['filename']})" for m in matches if m['type'] == 'mandatory'])
    optional_context = "\n".join([f"- {m['content']} (Source: {m['filename']})" for m in matches if m['type'] == 'optional'])
    
    prompt = f"""
    You are a professional translator for technical and development cooperation texts.
    Translate the following text from {source_lang} to {target_lang}.
    
    Input Text: "{segment_text}"
    
    Instructions:
    - Maintain the tone and style of the input.
    - PREFER terminology found in the MANDATORY REFERENCES below.
    - Use OPTIONAL REFERENCES for style/context inspiration.
    - Return ONLY the translated text, no explanations.
    - Preserve XML tags like <1>...</1> exactly if present.
    
    """
    
    if mandatory_context:
        prompt += f"\nMANDATORY REFERENCES (Must follow terminology):\n{mandatory_context}\n"
        
    if optional_context:
        prompt += f"\nOPTIONAL REFERENCES (Context/Inspiration):\n{optional_context}\n"
        
    # 3. Call Gemini
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        draft = response.text.strip()
    except Exception as e:
        print(f"Generation error: {e}")
        draft = "" # Fail gracefully
        
    return {
        "target_text": draft,
        "context_matches": matches
    }
