from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class TranslationMatch(BaseModel):
    """
    Represents a single retrieval match (TM or Vector).
    """
    id: str
    content: str = ""  # The target text (or source if source match)
    source_text: Optional[str] = None # For TM matches
    filename: str
    type: str # 'mandatory', 'user', 'optional', 'glossary', 'mt'
    category: str # 'legal', 'background', 'tm', 'term', 'ai'
    score: int # 0-100
    raw_logit: float = 0.0 # For debugging
    note: Optional[str] = None # Context note (Glossary)
    
    # Additional Context
    chunk_index: Optional[int] = None
    file_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SegmentContext(BaseModel):
    """
    Aggregated context for a specific segment.
    """
    matches: List[TranslationMatch] = []
    
    # Neighborhood Context (Surrounding segments from the same document)
    prev_chunks: List[str] = []
    next_chunks: List[str] = []
    
    # Glossary Hits (Separate from matches if needed, but usually integrated)
    glossary_hits: List[TranslationMatch] = []
    
    # Usage Stats (Retrieval Cost)
    retrieval_usage: Dict[str, int] = {}

class GenerationResult(BaseModel):
    """
    Result from the Inference Orchestrator.
    """
    target_text: str
    usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    context_used: SegmentContext
    is_exact: bool = False
    error: Optional[str] = None
    retrieval_usage: Dict[str, int] = {}
