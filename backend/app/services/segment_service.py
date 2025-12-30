

import os
import datetime
from collections import defaultdict, deque
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment, ProjectFile, ProjectFileCategory, AiUsageLog
from ..storage import download_file
from ..parser import parse_docx
from ..logger import get_logger
from ..schemas import SegmentInternal
from ..config import get_default_model_id
# Import RAG capability inside method or here if no circular dep?
# rag imports often import models/db so check circular. 
# safely import inside method if needed, but top level is cleaner if safe.
# We will import inside method to be safe as `rag` modules might be heavy.

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
        """
        Returns all segments for a project. 
        Note: The Segment model has properties for tags, metadata, and context_matches 
        that map to metadata_json, allowing direct Pydantic serialization.
        """
        return self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()

    async def generate_and_log_draft(self, segment_id: str, mode: str = "translate", is_workflow: bool = False, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Handles AI draft generation, including configuration lookup, RAG call, 
        metadata updates, and usage logging.
        """
        segment = self.db.query(Segment).filter(Segment.id == segment_id).first()
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")
            
        project = self.db.query(Project).filter(Project.id == segment.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 1. Workflow Shortcut: Copy Source
        if mode == "copy_source":
             # Direct Copy: Bypass RAG
             segment.target_content = segment.source_content
             segment.status = "translated"
             
             # Safe Metadata Update
             md = dict(segment.metadata_json) if segment.metadata_json else {}
             md["last_modified"] = datetime.datetime.utcnow().isoformat()
             segment.metadata_json = md
             
             self.db.commit()
             self.db.refresh(segment)
             
             # Return formatted response structure expected by schema
             return {
                 "id": segment.id,
                 "index": segment.index,
                 "source_content": segment.source_content,
                 "target_content": segment.target_content,
                 "status": segment.status,
                 "project_id": segment.project_id,
                 "context_matches": [],
                 "segment_metadata": md.get("metadata"),
                 "tags": md.get("tags")
             }

        # 2. AI Configuration
        config = project.config if project.config else {}
        ai_settings = config.get("ai_settings", {})
        
        default_model = ai_settings.get("model") or get_default_model_id()
        model_name = default_model
        if is_workflow:
             model_name = ai_settings.get("workflow_model") or default_model

        custom_prompt = ai_settings.get("custom_prompt", "")
        skip_ai = (mode == "analyze")

        # 3. Call RAG
        # Delayed import to avoid circular dependencies if any
        from ..rag import generate_segment_draft_v2

        try:
            result_dict = await generate_segment_draft_v2(
                segment_id=segment.id,
                project_id=str(project.id),
                db=self.db,
                model_name=model_name,
                custom_prompt=custom_prompt,
                skip_ai=skip_ai
            )
            
            target_text = result_dict.get("target_text", "")
            context_used = result_dict.get("context_used", {})
            context_matches = context_used.get("matches", [])
            usage = result_dict.get("usage", {})
            error = result_dict.get("error")
            
            if error:
                logger.error(f"Draft generation failed: {error}")
                raise HTTPException(status_code=500, detail=f"Analysis failed: {error}")
            
            # 4. Update Segment
            current_meta = dict(segment.metadata_json or {})
            
            # Ensure inner metadata dict exists (This is what is exposed as 'metadata' in Schema)
            inner_meta = current_meta.get("metadata", {})
            if not isinstance(inner_meta, dict): inner_meta = {}
            
            current_meta['context_matches'] = context_matches
            
            if mode == "translate":
                segment.target_content = target_text
                inner_meta['ai_draft'] = target_text
            elif mode == "draft":
                inner_meta['ai_draft'] = target_text
            
            # 5. Log Usage
            if usage:
                # Log to DB
                new_log = AiUsageLog(
                    project_id=project.id,
                    segment_id=segment.id,
                    model=model_name,
                    trigger_type="generation",
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0)
                )
                self.db.add(new_log)
                
                # Update Project Stats
                current_config = dict(project.config or {})
                usage_stats = current_config.get("usage_stats", {})
                model_stats = usage_stats.get(model_name, {"input_tokens": 0, "output_tokens": 0})
                
                model_stats["input_tokens"] += usage.get("input_tokens", 0)
                model_stats["output_tokens"] += usage.get("output_tokens", 0)
                
                usage_stats[model_name] = model_stats
                current_config["usage_stats"] = usage_stats
                project.config = current_config
                flag_modified(project, "config")
                
            inner_meta['ai_model'] = model_name
            current_meta['metadata'] = inner_meta # Save back nested
            segment.metadata_json = current_meta
            flag_modified(segment, "metadata_json")
            
            self.db.commit()
            self.db.refresh(segment)
            
            # Format Response
            resp_dict = segment.__dict__.copy()
            resp_dict['context_matches'] = context_matches
            
            meta_json = segment.metadata_json or {}
            resp_dict['segment_metadata'] = meta_json.get("metadata")
            resp_dict['tags'] = meta_json.get("tags")
            
            return resp_dict

        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logger.error(f"Generate Draft Error: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    def bulk_copy_source_to_target(self, project_id: str):
        """
        Copies source content to target content for all segments in a project.
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        try:
            self.db.query(Segment).filter(Segment.project_id == project_id).update(
                {
                    Segment.target_content: Segment.source_content,
                    Segment.status: "translated",
                },
                synchronize_session=False
            )
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Bulk copy failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def process_batch_translation(self, project_id: str, segment_ids: List[str], mode: str = "draft"):
        """
        Batched Translation Workflow.
        mode="draft": Update ai_draft only, status=draft.
        mode="translate": Update target_content and ai_draft, status=translated.
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        config = project.config or {}
        ai_settings = config.get("ai_settings", {})
        model_name = ai_settings.get("workflow_model") or get_default_model_id() # Use Faster Model!
        custom_prompt = ai_settings.get("custom_prompt", "")

        from ..rag import RAGManager
        manager = RAGManager(project_id, self.db)
        
        try:
            # Call Batch Draft Generation
            results = await manager.generate_batch_draft(
                segment_ids=segment_ids,
                source_lang=project.source_lang,
                target_lang=project.target_lang,
                model_name=model_name,
                custom_prompt=custom_prompt
            )
            
            # Bulk Update DB
            total_input_tokens = 0
            total_output_tokens = 0
            
            # We fetch segments again to update them in session? Or just iterate results
            # Results dict keyed by ID.
            
            segments = self.db.query(Segment).filter(Segment.id.in_(results.keys())).all()
            
            for seg in segments:
                res = results.get(seg.id)
                if not res: continue
                
                # FIX: Convert Pydantic models to Dicts for JSON serialization
                context_matches = [m.model_dump() for m in res.context_used.matches] if res.context_used else []
                
                current_meta = dict(seg.metadata_json or {})
                
                # Nested Metadata
                inner_meta = current_meta.get("metadata", {})
                if not isinstance(inner_meta, dict): inner_meta = {}

                current_meta['context_matches'] = context_matches
                inner_meta['ai_model'] = model_name
                
                target_text = res.target_text
                
                if mode == "translate":
                   seg.target_content = target_text
                   inner_meta['ai_draft'] = target_text
                   if not res.is_exact: # If exact match, maybe status is approved? or translated?
                       seg.status = "translated" 
                elif mode == "draft":
                   inner_meta['ai_draft'] = target_text
                   
                current_meta['metadata'] = inner_meta 
                seg.metadata_json = current_meta
                flag_modified(seg, "metadata_json")
                
                # Accumulate Usage
                if res.usage:
                    total_input_tokens += res.usage.get("input_tokens", 0)
                    total_output_tokens += res.usage.get("output_tokens", 0)
                    
            # Log Aggregate Usage
            if total_input_tokens > 0 or total_output_tokens > 0:
                 # Log to Project Stats
                 usage_stats = config.get("usage_stats", {})
                 model_stats = usage_stats.get(model_name, {"input_tokens": 0, "output_tokens": 0})
                 model_stats["input_tokens"] += total_input_tokens
                 model_stats["output_tokens"] += total_output_tokens
                 usage_stats[model_name] = model_stats
                 config["usage_stats"] = usage_stats
                 project.config = config
                 flag_modified(project, "config")
                 
                 # Add a single Log entry for the batch? Or per segment?
                 # Per segment is cleaner for detailed stats but spammy. 
                 # Let's log a meaningful "Batch" entry?
                 # AiUsageLog requires segment_id.
                 # We will skip per-segment logging for batch workflow to save DB space, 
                 # OR log one entry with segment_id=None (if nullable)? 
                 # Model says segment_id is ForeignKey. 
                 # We'll just skip detailed logs and rely on Project Stats for cost tracking.
                 pass

            self.db.commit()
            return {"status": "success", "processed": len(results)}
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Batch Process Failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
