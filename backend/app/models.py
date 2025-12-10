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
    status = Column(String, default=ProjectStatus.processing.value) # Storing as string for simplicity with SQLite
    created_at = Column(DateTime, default=datetime.utcnow)
    source_lang = Column(String, default="en")
    target_lang = Column(String, default="de")
    use_clean_template = Column(Boolean, default=False)
    config = Column(JSON, nullable=True) # Extra config if needed

    segments = relationship("Segment", back_populates="project", cascade="all, delete-orphan")

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
