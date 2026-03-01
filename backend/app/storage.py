"""
Local filesystem storage — drop-in replacement for the old MinIO backend.
Files are stored under STORAGE_ROOT / {project_id} / {category} / {filename}.

Configure via env var:
    STORAGE_ROOT=./projectdata      (default, relative to backend working dir)
"""

import os
import shutil
import logging

logger = logging.getLogger("Storage")

STORAGE_ROOT = os.getenv("STORAGE_ROOT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "projectdata"))


def _full_path(object_name: str) -> str:
    """Resolve an object name (e.g. '{project_id}/source/doc.docx') to an absolute local path."""
    return os.path.join(STORAGE_ROOT, object_name)


def ensure_bucket_exists():
    """Create the storage root directory if it doesn't exist."""
    os.makedirs(STORAGE_ROOT, exist_ok=True)


def upload_file(file_data, object_name: str, content_type: str = "application/octet-stream") -> str:
    """
    Save file_data (bytes or file-like object) to local storage.
    Returns the object_name (unchanged, for DB storage).
    """
    dest = _full_path(object_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if isinstance(file_data, bytes):
        with open(dest, "wb") as f:
            f.write(file_data)
    else:
        # File-like object (e.g. SpooledTemporaryFile from FastAPI UploadFile)
        file_data.seek(0)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file_data, f)

    logger.info(f"Stored: {object_name} ({os.path.getsize(dest)} bytes)")
    return object_name


def download_file(object_name: str, file_path: str):
    """
    Copy a stored file to a local target path (used by export, parsing, ingestion).
    """
    src = _full_path(object_name)
    if not os.path.exists(src):
        raise FileNotFoundError(f"Storage file not found: {object_name}")
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    shutil.copy2(src, file_path)


def delete_file(object_name: str):
    """Delete a file from local storage. Silently ignores missing files."""
    path = _full_path(object_name)
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Deleted: {object_name}")


def delete_project_folder(project_id: str):
    """Delete the entire project folder from local storage."""
    folder = os.path.join(STORAGE_ROOT, project_id)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        logger.info(f"Deleted project folder: {project_id}")


def copy_file(source_object_name: str, dest_object_name: str):
    """Copy a file within local storage (used by project duplication)."""
    src = _full_path(source_object_name)
    dest = _full_path(dest_object_name)
    if not os.path.exists(src):
        raise FileNotFoundError(f"Source file not found: {source_object_name}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    logger.info(f"Copied: {source_object_name} -> {dest_object_name}")


def get_file_url(object_name: str) -> str:
    """Return the absolute local path (replaces presigned URL concept)."""
    return _full_path(object_name)
