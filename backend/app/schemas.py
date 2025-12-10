from pydantic import BaseModel
from typing import Dict, Optional, Any
from datetime import datetime

class TagModel(BaseModel):
    """
    Represents a tag (formatting, comment, etc.)
    Example: { "type": "bold", "xml_attributes": {...} }
    """
    type: str
    ref_id: Optional[str] = None # For comments or mappings
    content: Optional[str] = None # For comment content
    xml_attributes: Optional[Dict[str, Any]] = None

class ProjectCreate(BaseModel):
    pass # Upload creates project, usually no body needed or just config

class ProjectResponse(BaseModel):
    id: str
    filename: str
    status: str
    created_at: datetime
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    
    class Config:
        from_attributes = True

class SegmentResponse(BaseModel):
    id: str
    index: int
    source_content: str
    target_content: Optional[str] = None
    status: str
    project_id: str
    
    class Config:
        from_attributes = True
        populate_by_name = True

class SegmentInternal(BaseModel):
    """
    Internal representation of a parsed segment.
    """
    segment_id: str
    source_text: str # Text with <n> tags
    target_content: Optional[str] = None
    tags: Dict[str, TagModel] # Map of "1" -> TagModel
    metadata: Optional[Dict[str, Any]] = None
