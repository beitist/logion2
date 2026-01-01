
import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..models import Project, ProjectFile, ProjectFileCategory, Segment, GlossaryEntry, TranslationUnit, AiUsageLog
from ..storage import upload_file, download_file
from ..document.parser import parse_document
from ..logger import get_logger
from ..workflows.reingest import run_background_reingest

logger = get_logger("ProjectService")
UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    async def create_project(
        self,
        name: str,
        source_lang: str,
        target_lang: str,
        use_ai: bool,
        background_tasks: BackgroundTasks,
        source_files: Optional[List[UploadFile]] = None,
        legal_files: Optional[List[UploadFile]] = None,
        background_files: Optional[List[UploadFile]] = None
    ) -> Project:
        project_id = str(uuid.uuid4())
        
        # Create Project Record
        new_project = Project(
            id=project_id,
            name=name,
            filename=source_files[0].filename if source_files else "Untitled",
            status="processing",
            source_lang=source_lang,
            target_lang=target_lang,
            use_ai=use_ai,
            created_at=datetime.utcnow()
        )
        self.db.add(new_project)
        self.db.commit()

        # Process all file categories
        for f in source_files or []:
            await self._process_file(f, ProjectFileCategory.source, project_id)
            
        for f in legal_files or []:
            await self._process_file(f, ProjectFileCategory.legal, project_id)
            
        for f in background_files or []:
            await self._process_file(f, ProjectFileCategory.background, project_id)
        
        self.db.commit()

        # Parse segments if we have a source docx
        await self._parse_initial_source(new_project)

        # Trigger RAG Ingestion (Background)
        if use_ai:
            background_tasks.add_task(run_background_reingest, new_project.id)

        self.db.refresh(new_project)
        return new_project

    async def _process_file(self, file: UploadFile, category: ProjectFileCategory, project_id: str):
        if not file.filename:
            return
        
        object_name = f"{project_id}/{category.value}/{file.filename}"
        
        try:
            await file.seek(0)
            uploaded_obj = upload_file(file.file, object_name, content_type=file.content_type)
            
            db_file = ProjectFile(
                id=str(uuid.uuid4()),
                project_id=project_id,
                category=category.value,
                filename=file.filename,
                file_path=uploaded_obj
            )
            self.db.add(db_file)
            
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}", exc_info=True)
            # Continue despite upload error?

    async def _parse_initial_source(self, project: Project):
        source_record = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == project.id,
            ProjectFile.category == ProjectFileCategory.source.value
        ).first()
        
        if source_record:
            from ..document.parsing_service import process_file_parsing
            
            try:
                # Use unified helper
                segments_internal = process_file_parsing(
                    file_path_or_url=source_record.file_path,
                    project_id=project.id,
                    source_lang=project.source_lang,
                    original_filename=source_record.filename
                )
                
                for i, seg_int in enumerate(segments_internal):
                    seg_dump = seg_int.model_dump()
                    db_segment = Segment(
                        id=seg_int.segment_id,
                        project_id=project.id,
                        index=i,
                        source_content=seg_int.source_text,
                        target_content=None,
                        status="draft",
                        metadata_json=seg_dump
                    )
                    self.db.add(db_segment)
                
                project.status = "review"
                self.db.add(project)
                self.db.commit()
                
            except Exception as e:
                self.db.delete(project)
                self.db.commit()
                # logger.error ...
                raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_all_projects(self) -> List[Project]:
        projects = self.db.query(Project).order_by(Project.created_at.desc()).all()
        
        # Calculate Progress (Simplistic approach: N+1, optimize if needed)
        for p in projects:
            total = len(p.segments)
            if total == 0:
                p.progress = 0
            else:
                completed = sum(1 for s in p.segments if s.status in ["translated", "approved", "completed"])
                p.progress = int((completed / total) * 100)
                
        return projects


    def delete_project(self, project_id: str):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Delete AI usage logs first (referenced by segments)
        self.db.query(AiUsageLog).filter(AiUsageLog.project_id == project_id).delete()
        
        # Delete segments manually
        self.db.query(Segment).filter(Segment.project_id == project_id).delete()
        # Delete glossary entries manually
        self.db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).delete()
        # Delete translation units manually
        self.db.query(TranslationUnit).filter(TranslationUnit.project_id == project_id).delete()
        
        self.db.delete(project)
        self.db.commit()

    def duplicate_project(self, project_id: str) -> Project:
        original = self.get_project(project_id)
        if not original:
            raise HTTPException(status_code=404, detail="Project not found")

        new_id = str(uuid.uuid4())
        new_project = Project(
            id=new_id,
            name=f"Copy of {original.name}",
            filename=original.filename,
            status=original.status, 
            rag_status="created", 
            source_lang=original.source_lang,
            target_lang=original.target_lang,
            use_ai=original.use_ai,
            config=original.config,
            created_at=datetime.utcnow()
        )
        self.db.add(new_project)
        
        # 1. Duplicate Files
        from ..storage import copy_file
        
        for f in original.files:
            new_file_id = str(uuid.uuid4())
            new_object_name = f"{new_id}/{f.category}/{f.filename}"
            
            try:
                copy_file(f.file_path, new_object_name)
                
                new_file = ProjectFile(
                    id=new_file_id,
                    project_id=new_id,
                    category=f.category,
                    filename=f.filename,
                    file_path=new_object_name,
                    uploaded_at=datetime.utcnow()
                )
                self.db.add(new_file)
            except Exception as e:
                logger.error(f"Failed to copy file {f.filename}: {e}")

        # 2. Duplicate Segments
        for seg in original.segments:
            new_seg = Segment(
                id=str(uuid.uuid4()),
                project_id=new_id,
                index=seg.index,
                source_content=seg.source_content,
                target_content=seg.target_content,
                status=seg.status,
                metadata_json=seg.metadata_json
            )
            self.db.add(new_seg)

        # 3. Duplicate Glossary
        glossary_entries = self.db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).all()
        for entry in glossary_entries:
            new_entry = GlossaryEntry(
                id=str(uuid.uuid4()),
                project_id=new_id,
                source_term=entry.source_term,
                target_term=entry.target_term,
                source_lemma=entry.source_lemma,
                context_note=entry.context_note
            )
            self.db.add(new_entry)


        self.db.commit()
        self.db.refresh(new_project)
        return new_project
        
    def update_project(self, project_id: str, update_data: dict) -> Project:
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        for key, value in update_data.items():
            setattr(project, key, value)
        
        self.db.commit()
        self.db.refresh(project)
        return project

    def trigger_reingestion(self, project_id: str, background_tasks: BackgroundTasks):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        background_tasks.add_task(run_background_reingest, project_id)

    def trigger_draft_generation(self, project_id: str, background_tasks: BackgroundTasks):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        from ..workflows.batch_draft import run_background_batch_draft
        background_tasks.add_task(run_background_batch_draft, project_id)

    def trigger_preload_matches(self, project_id: str, background_tasks: BackgroundTasks):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        from ..workflows.preload_matches import run_background_preload_matches
        background_tasks.add_task(run_background_preload_matches, project_id)
