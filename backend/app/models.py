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

    project = relationship("Project", back_populates="segments")

# --- RAG Models ---
from pgvector.sqlalchemy import Vector

class ContextChunk(Base):
    """Stores vector embeddings for RAG"""
    __tablename__ = "context_chunks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False)
    
    content = Column(Text, nullable=False) # The chunk text
    embedding = Column(Vector(768)) # Google text-embedding-004
    
    # We link back to the file, which links to the project.
    file = relationship("ProjectFile", back_populates="chunks")

# Update relationships in ProjectFile
ProjectFile.chunks = relationship("ContextChunk", back_populates="file", cascade="all, delete-orphan")

