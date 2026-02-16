

import os
import datetime
from collections import defaultdict, deque
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from ..models import Segment, Project, AiUsageLog
from ..schemas import SegmentInternal
from ..logger import get_logger
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

    def reinitialize_project(self, project_id: str, background_tasks: BackgroundTasks, new_file_upload: Optional[Any] = None) -> Project:
        """
        Delegates to ReinitializeWorkflow.
        """
        from ..workflows.reinitialize import ReinitializeWorkflow, run_background_vector_regen
        
        # Run Sync Logic
        wf = ReinitializeWorkflow(self.db, project_id)
        project = wf.run(new_file_upload)
        
        # Trigger Background Logic
        background_tasks.add_task(run_background_vector_regen, project_id)
        
        return project



    def get_segments(self, project_id: str) -> List[Segment]:
        """
        Returns all segments for a project. 
        Note: The Segment model has properties for tags, metadata, and context_matches 
        that map to metadata_json, allowing direct Pydantic serialization.
        """
        return self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()

    async def generate_and_log_draft(self, segment_id: str, mode: str = "translate", is_workflow: bool = False, force_refresh: bool = False, tc_params=None) -> Dict[str, Any]:
        """
        Handles AI draft generation, including configuration lookup, RAG call,
        metadata updates, and usage logging.

        If tc_params is provided, translates the TC stage source text and diffs
        against the base translation to produce TC markup.
        """
        segment = self.db.query(Segment).filter(Segment.id == segment_id).first()
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        project = self.db.query(Project).filter(Project.id == segment.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # TC-aware single-segment MT: translate stage source, diff with base
        if tc_params is not None:
            return await self._generate_tc_draft(segment, project, tc_params)

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
            
            # Merge Glossary Hits so they appear in UI
            glossary_hits = context_used.get("glossary_hits", [])
            if glossary_hits:
                context_matches.extend(glossary_hits)
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
            
            # 5. Log Usage (LLM + Retrieval)
            usages_to_log = []
            
            # A. Generation Usage
            if usage:
                usages_to_log.append({
                    "model": model_name,
                    "input": usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                    "type": "generation"
                })
                
            # B. Retrieval Usage
            retrieval_usage = result_dict.get("retrieval_usage", {})
            for r_model, r_tokens in retrieval_usage.items():
                if r_tokens > 0:
                    usages_to_log.append({
                        "model": r_model,
                        "input": r_tokens,
                        "output": 0,
                        "type": "retrieval"
                    })

            if usages_to_log:
                current_config = dict(project.config or {})
                usage_stats = current_config.get("usage_stats", {})
                
                for u in usages_to_log:
                    # Log to DB
                    self.db.add(AiUsageLog(
                        project_id=project.id,
                        segment_id=segment.id,
                        model=u['model'],
                        trigger_type=u['type'],
                        input_tokens=u['input'],
                        output_tokens=u['output']
                    ))
                    
                    # Update Project Stats
                    m_stats = usage_stats.get(u['model'], {"input_tokens": 0, "output_tokens": 0})
                    m_stats["input_tokens"] += u['input']
                    m_stats["output_tokens"] += u['output']
                    usage_stats[u['model']] = m_stats
                
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
            resp_dict.pop('embedding', None) # Exclude large vector
            resp_dict.pop('_sa_instance_state', None) # Cleanup SQLAlchemy state
            
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

    async def _generate_tc_draft(self, segment: Segment, project: Project, tc_params) -> Dict[str, Any]:
        """
        Translates the TC stage source text and diffs against the base translation
        to produce TC markup with <insert>/<delete> tags.
        """
        from ..rag.inference import InferenceOrchestrator
        from ..utils.tc_diff import generate_tc_markup

        config = project.config or {}
        ai_settings = config.get("ai_settings", {})
        model_name = ai_settings.get("workflow_model") or ai_settings.get("model") or get_default_model_id()
        custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")

        orchestrator = InferenceOrchestrator()

        # If base translation exists, use revision prompt + TM reference
        # so the MT revises rather than re-translates (cleaner diffs)
        base = tc_params.tc_base_translation or ""
        tm_matches = []
        if base:
            custom_prompt += (
                "\n\nIMPORTANT: A reference translation is provided as TM match. "
                "The source text was revised compared to the reference source. "
                "Update the reference translation to reflect the source changes only. "
                "Keep wording identical where the source has not changed."
            )
            tm_matches = [{"source": segment.source_content, "target": base, "score": 95}]

        try:
            translations, usage = await orchestrator.generate_structured_batch(
                preceding_context=[],
                following_context=[],
                batch_items=[{
                    "id": str(segment.id),
                    "source_text": tc_params.tc_source_text,
                    "tm_matches": tm_matches,
                    "glossary_matches": [],
                }],
                source_lang=project.source_lang,
                target_lang=project.target_lang,
                model_name=model_name,
                custom_prompt=custom_prompt,
            )

            stage_translation = translations.get(str(segment.id), "")

            if not stage_translation:
                raise HTTPException(status_code=500, detail="TC stage translation returned empty")

            # Diff against base translation to produce TC markup
            base = tc_params.tc_base_translation or ""
            if base and stage_translation != base:
                tc_content = generate_tc_markup(
                    old_text=base,
                    new_text=stage_translation,
                    author_id=tc_params.tc_author_id,
                    author_name=tc_params.tc_author_name,
                    date=tc_params.tc_date,
                )
            else:
                tc_content = stage_translation

            segment.target_content = tc_content
            segment.status = "translated"

            # Update metadata
            current_meta = dict(segment.metadata_json or {})
            inner_meta = current_meta.get("metadata", {})
            if not isinstance(inner_meta, dict):
                inner_meta = {}
            inner_meta["ai_model"] = model_name
            inner_meta["tc_stage_translation"] = stage_translation
            current_meta["metadata"] = inner_meta
            segment.metadata_json = current_meta
            flag_modified(segment, "metadata_json")

            # Log usage
            if usage:
                self.db.add(AiUsageLog(
                    project_id=project.id,
                    segment_id=segment.id,
                    model=model_name,
                    trigger_type="tc_single",
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                ))

                current_config = dict(project.config or {})
                usage_stats = current_config.get("usage_stats", {})
                m_stats = usage_stats.get(model_name, {"input_tokens": 0, "output_tokens": 0})
                m_stats["input_tokens"] += usage.get("input_tokens", 0)
                m_stats["output_tokens"] += usage.get("output_tokens", 0)
                usage_stats[model_name] = m_stats
                current_config["usage_stats"] = usage_stats
                project.config = current_config
                flag_modified(project, "config")

            self.db.commit()
            self.db.refresh(segment)

            resp_dict = segment.__dict__.copy()
            resp_dict.pop('embedding', None)
            resp_dict.pop('_sa_instance_state', None)
            meta_json = segment.metadata_json or {}
            resp_dict['context_matches'] = meta_json.get("context_matches", [])
            resp_dict['segment_metadata'] = meta_json.get("metadata")
            resp_dict['tags'] = meta_json.get("tags")
            return resp_dict

        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logger.error(f"TC Draft Error: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    def bulk_copy_source_to_target(self, project_id: str):
        """
        Copies source content to target content for all segments in a project.
        Uses CopySourceWorkflow (Synchronous).
        """
        from ..workflows.copy_source import CopySourceWorkflow
        wf = CopySourceWorkflow(self.db, project_id)
        # wf.run() # Sync
        # We can just call run.
        wf.run()

    def process_batch_translation(self, project_id: str, background_tasks: BackgroundTasks, segment_ids: List[str], mode: str = "draft"):
        """
        Batched Translation Workflow (Background).
        Delegates to BatchTranslateWorkflow.
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        from ..workflows.batch_translate import run_background_batch_translate
        background_tasks.add_task(run_background_batch_translate, project_id, segment_ids)
        
        return {"status": "started", "message": "Batch translation started in background"}

    def process_tc_batch(self, project_id: str, background_tasks: BackgroundTasks, segment_ids: List[str] = None):
        """
        TC Step-by-Step Batch Workflow (Background).
        Translates each revision stage and diffs them into TC markup.
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        from ..workflows.tc_batch import run_background_tc_batch
        background_tasks.add_task(run_background_tc_batch, project_id, segment_ids)

        return {"status": "started", "message": "TC batch translation started in background"}
