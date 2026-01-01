
import os
import shutil
from typing import List, Optional, Any
from app.document.parser.main import parse_document
from app.storage import download_file
from app.schemas import SegmentInternal

UPLOAD_DIR = "uploads" # Should match where it is used elsewhere, or be config

def process_file_parsing(
    file_path_or_url: str, 
    project_id: str, 
    source_lang: str = "en",
    original_filename: str = None
) -> List[SegmentInternal]:
    """
    Unified helper to download/copy a file to a temp location with correct extension,
    parse it, and return the segments.
    
    Args:
        file_path_or_url: Local path or storage key/URL to download.
        project_id: ID for temp file naming.
        source_lang: Language for sentence splitting.
        original_filename: Used to determine extension if not obvious from file_path.
    """
    
    # Determine extension
    ext = ".docx" # Default
    if original_filename:
        _, ext = os.path.splitext(original_filename)
        if not ext: ext = ".docx"
    elif file_path_or_url:
        _, ext = os.path.splitext(file_path_or_url)
        if not ext: ext = ".docx"

    # Normalize extension
    ext = ext.lower()

    temp_path = os.path.join(UPLOAD_DIR, f"temp_parse_{project_id}{ext}")
    
    try:
        # Check if it is a local upload (UploadFile) or remote/storage path
        # If it's an absolute local path that exists, we might copy it?
        # But our usage pattern usually involves `download_file` from minio/gcs OR reading UploadFile.
        
        # NOTE: This helper assumes `download_file` handles the abstraction.
        # If caller provides an open file stream, handle differently?
        # Current usage: ProjectService uses `download_file`.
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        download_file(file_path_or_url, temp_path)
        
        return parse_document(temp_path, source_lang=source_lang)
        
    finally:
         if os.path.exists(temp_path):
             os.remove(temp_path)

def save_upload_to_temp(upload_file: Any, project_id: str) -> str:
    """
    Saves a FastAPI UploadFile to a temp path and returns the path.
    """
    _, ext = os.path.splitext(upload_file.filename)
    temp_path = os.path.join(UPLOAD_DIR, f"temp_upload_{project_id}{ext}")
    
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(upload_file.file, f)
    return temp_path
