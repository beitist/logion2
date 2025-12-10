from pydantic import BaseModel
from typing import Dict, Optional, Any

class TagModel(BaseModel):
    """
    Represents a tag (formatting, comment, etc.)
    Example: { "type": "bold", "xml_attributes": {...} }
    """
    type: str
    ref_id: Optional[str] = None # For comments or mappings
    content: Optional[str] = None # For comment content
    xml_attributes: Optional[Dict[str, Any]] = None

class SegmentInternal(BaseModel):
    """
    Internal representation of a parsed segment.
    """
    segment_id: str
    source_text: str # Text with <n> tags
    target_content: Optional[str] = None
    tags: Dict[str, TagModel] # Map of "1" -> TagModel
    metadata: Optional[Dict[str, Any]] = None
