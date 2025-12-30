from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, JSON, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from .database import Base

class ProjectStatus(str, enum.Enum):
    processing = "processing"
    review = "review"
    completed = "completed"

class SegmentStatus(str, enum.Enum):
    draft = "draft"
    translated = "translated"
    error = "error"

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    name = Column(String, nullable=True) # Project Name
    status = Column(String, default=ProjectStatus.processing.value) 
    rag_status = Column(String, default="created") # created, ingesting, ready, error 
    created_at = Column(DateTime, default=datetime.utcnow)
    source_lang = Column(String, default="en")
    target_lang = Column(String, default="de")
    use_clean_template = Column(Boolean, default=False)
    use_ai = Column(Boolean, default=False)
    file_hash = Column(String, nullable=True) 
    config = Column(JSON, nullable=True) 
    ingestion_logs = Column(JSON, default=[]) # List of log strings 
    rag_progress = Column(Integer, default=0) # percent 0-100 

    segments = relationship("Segment", back_populates="project", cascade="all, delete-orphan")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")

class ProjectFileCategory(str, enum.Enum):
    source = "source"
    legal = "legal"
    background = "background"

class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    category = Column(String, default=ProjectFileCategory.source.value)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="files")

class Segment(Base):
    __tablename__ = "segments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    index = Column(Integer, nullable=False)
    source_content = Column(Text, nullable=False) # Stores the text with XML tags <n>...</n>
    target_content = Column(Text, nullable=True)
    status = Column(String, default=SegmentStatus.draft.value)
    metadata_json = Column(JSON, nullable=True) # Renamed to avoid confusion with internal metadata
    embedding = Column(Vector(768)) # Pre-calculated Source Vector


    project = relationship("Project", back_populates="segments")

    @property
    def tags(self):
        return (self.metadata_json or {}).get("tags")

    @property
    def segment_metadata(self):
        return (self.metadata_json or {}).get("metadata")

    @property
    def context_matches(self):
        return (self.metadata_json or {}).get("context_matches")


# --- RAG Models ---
from pgvector.sqlalchemy import Vector

class ContextChunk(Base):
    """Stores vector embeddings for RAG"""
    __tablename__ = "context_chunks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False)
    
    content = Column(Text, nullable=False) # The chunk text (Plain for embedding)
    rich_content = Column(Text, nullable=True) # The chunk text with Tags (<1>...</1>)
    embedding = Column(Vector(768)) # LaBSE Embeddings
    
    # Retrieval Optimization
    chunk_index = Column(Integer, nullable=True, index=True) # Position in file (0, 1, 2...) for Context Window
    
    # Semantic Alignment Fields
    source_segment = Column(Text, nullable=True) # Aligned Source (1 or 2 sent)
    target_segment = Column(Text, nullable=True) # Aligned Target (1 or 2 sent)
    alignment_score = Column(Integer, nullable=True) # 0-100 Confidence
    alignment_type = Column(String, nullable=True) # '1:1', '2:1', '1:2'
    
    # We link back to the file, which links to the project.
    file = relationship("ProjectFile", back_populates="chunks")

# Update relationships in ProjectFile
ProjectFile.chunks = relationship("ContextChunk", back_populates="file", cascade="all, delete-orphan")

class TranslationOrigin(str, enum.Enum):
    mandatory = "mandatory"
    user = "user"
    optional = "optional"

class TranslationOrigin(str, enum.Enum):
    mandatory = "mandatory"
    user = "user"
    optional = "optional"

class TranslationMemoryUnit(Base):
    """
    Vector-Enabled Translation Memory (Replaces ChromaDB)
    """
    __tablename__ = "tm_vectors"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Text Content
    source_text = Column(Text, nullable=False) # STRIPPED source for embedding/search
    target_text = Column(Text, nullable=False) 
    
    # Metadata for Display
    raw_source = Column(Text, nullable=False) # Original Source with Tags/Tabs
    source_lang = Column(String, default="en")
    target_lang = Column(String, default="de")
    
    # Vector
    # Using 384 dimensions for all-MiniLM-L6-v2 (default SentenceTransformer)
    embedding = Column(Vector(384)) 
    
    created_at = Column(DateTime, default=datetime.utcnow)

class TranslationUnit(Base):
    """Hybrid TMX / Exact Match Table"""
    __tablename__ = "translation_units"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, index=True, nullable=False)
    
    # Hashing for O(1) Lookup
    source_hash = Column(String, index=True, nullable=False) # SHA-256
    
    # Content
    source_text = Column(Text, nullable=False)
    target_text = Column(Text, nullable=False)
    
    # Metadata
    origin_type = Column(String, default=TranslationOrigin.user.value, index=True) # mandatory, user, optional
    
    # 101% Context
    context_prev = Column(String, nullable=True) # Hash of previous sentence
    context_next = Column(String, nullable=True) # Hash of next sentence
    
    created_at = Column(DateTime, default=datetime.utcnow)
    changed_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    creation_user = Column(String, nullable=True)

class GlossaryEntry(Base):
    __tablename__ = "glossary_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    
    source_term = Column(String, nullable=False) # e.g. "Final Reports"
    target_term = Column(String, nullable=False) # e.g. "Verwendungsnachweise"
    source_lemma = Column(String, index=True, nullable=False) # e.g. "final report" (SpaCy computed)
    
    context_note = Column(String, nullable=True) # e.g. "Bengo/BMZ specific"
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    project = relationship("Project")

class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    segment_id = Column(String, ForeignKey("segments.id"), nullable=True) # Optional link
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    model = Column(String, nullable=False)
    trigger_type = Column(String, default="manual") # manual, auto_translate, lookahead
    
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    
    # Optional: Cost (could be calculated later if rates change, but storing point-in-time cost is safer if rates vary)
    # cost = Column(Float, default=0.0) 

    # Relationship
    project = relationship("Project")

