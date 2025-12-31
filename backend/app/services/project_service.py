
import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..models import Project, ProjectFile, ProjectFileCategory, Segment, GlossaryEntry, TranslationUnit, AiUsageLog
from ..storage import upload_file, download_file
from ..parser import parse_docx
from ..logger import get_logger
from ..rag import ingest_project_files

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
            background_tasks.add_task(ingest_project_files, new_project.id)

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
            ProjectFile.category == ProjectFileCategory.source.value,
            ProjectFile.filename.endswith(".docx")
        ).first()
        
        if source_record:
            temp_parse_path = os.path.join(UPLOAD_DIR, f"temp_{project.id}.docx")
            try:
                download_file(source_record.file_path, temp_parse_path)
                
                segments_internal = parse_docx(temp_parse_path, source_lang=project.source_lang)
                
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
                raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
            finally:
                if os.path.exists(temp_parse_path):
                    os.remove(temp_parse_path)

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_all_projects(self) -> List[Project]:
        return self.db.query(Project).order_by(Project.created_at.desc()).all()


    def delete_project(self, project_id: str):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

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
            
        background_tasks.add_task(ingest_project_files, project_id)

    def trigger_draft_generation(self, project_id: str, background_tasks: BackgroundTasks):
        project = self.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        from ..rag import generate_project_drafts
        background_tasks.add_task(generate_project_drafts, project_id)

