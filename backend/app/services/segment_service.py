
import os
from collections import defaultdict, deque
from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..models import Project, Segment, ProjectFile, ProjectFileCategory, AiUsageLog
from ..storage import download_file
from ..parser import parse_docx
from ..logger import get_logger
from ..schemas import SegmentInternal

logger = get_logger("SegmentService")
UPLOAD_DIR = "uploads"

class SegmentService:
    def __init__(self, db: Session):
        self.db = db

    def reinitialize_project(self, project_id: str) -> Project:
        """
        Re-parses the source file but preserves existing translations by matching Source Text.
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 1. Find Source File
        source_record = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == project.id,
            ProjectFile.category == ProjectFileCategory.source.value,
            ProjectFile.filename.endswith(".docx")
        ).first()
        
        if not source_record:
            raise HTTPException(status_code=400, detail="No source DOCX file found to reinitialize.")

        # 2. Download and Parse Fresh
        temp_parse_path = os.path.join(UPLOAD_DIR, f"temp_reinit_{project_id}.docx")
        new_segments_internal = []
        try:
            if os.path.exists(temp_parse_path):
                 os.remove(temp_parse_path)
                 
            download_file(source_record.file_path, temp_parse_path)
            new_segments_internal = parse_docx(temp_parse_path, source_lang=project.source_lang)
            
        except Exception as e:
            logger.error(f"Reinitialization failed during parse: {e}")
            raise HTTPException(status_code=500, detail=f"Reinitialization parsing failed: {e}")
        finally:
             if os.path.exists(temp_parse_path):
                 os.remove(temp_parse_path)

        # 3. Fetch Old and Merge
        final_db_segments = self.merge_old_with_new(project_id, new_segments_internal)

        # 4. Atomic Replace
        try:
            # Unlink AI Usage Logs first
            self.db.query(AiUsageLog).filter(
                AiUsageLog.project_id == project_id
            ).update({AiUsageLog.segment_id: None}, synchronize_session=False)

            # Delete old
            self.db.query(Segment).filter(Segment.project_id == project_id).delete()
            
            # Insert new
            self.db.add_all(final_db_segments)
            self.db.commit()
            self.db.refresh(project)
            
            return project
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"DB Error during reinitialization: {e}")
            raise HTTPException(status_code=500, detail=f"Database update failed: {e}")

    def merge_old_with_new(self, project_id: str, new_segments_internal: List[SegmentInternal]) -> List[Segment]:
        """
        Merges existing segments (DB) with new parsed segments (List[SegmentInternal]).
        Matches by source_content using FIFO for duplicates.
        """
        old_segments = self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
        
        # Map Source Text -> Queue of Old Segments (FIFO)
        old_map = defaultdict(deque)
        for seg in old_segments:
            old_map[seg.source_content].append(seg)
            
        logger.info(f"Reinitializing Project {project_id}: Parsed {len(new_segments_internal)} new segments vs {len(old_segments)} old.")

        final_db_segments = []
        new_count = 0
        preserved_count = 0
        
        for i, new_seg_int in enumerate(new_segments_internal):
            target_content = None
            status = "draft"
            
            # Check for match
            if old_map[new_seg_int.source_text]:
                match = old_map[new_seg_int.source_text].popleft()
                target_content = match.target_content
                status = match.status
                preserved_count += 1
            else:
                new_count += 1
            
            seg_dump = new_seg_int.model_dump()
            
            new_db_seg = Segment(
                id=new_seg_int.segment_id,
                project_id=project_id,
                index=i,
                source_content=new_seg_int.source_text,
                target_content=target_content,
                status=status,
                metadata_json=seg_dump
            )
            final_db_segments.append(new_db_seg)
            
        logger.info(f"Reinit Success: Preserved {preserved_count}, Added {new_count}. Total {len(final_db_segments)}.")
        return final_db_segments

    def get_segments(self, project_id: str) -> List[Segment]:
        return self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
