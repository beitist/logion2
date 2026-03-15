import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment, AiUsageLog
from ..rag.manager import RAGManager
from ..database import SessionLocal
from .base import BaseWorkflow
from ..config import get_default_model_id

from typing import List, Optional

async def run_background_batch_draft(project_id: str, segment_ids: Optional[List[str]] = None):
    """
    Async Background Task for Draft Generation.
    """
    db = SessionLocal()
    try:
        wf = BatchDraftWorkflow(db, project_id)
        await wf.run(segment_ids)
    except Exception as e:
        print(f"Batch Draft Failed: {e}")
    finally:
        db.close()

class BatchDraftWorkflow(BaseWorkflow):
    async def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log(f"Starting Batch Draft Generation (Async)...")
            
            # Fetch segments
            query = self.db.query(Segment).filter(Segment.project_id == self.project_id)
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))
            
            all_segments = query.order_by(Segment.index).all()
            if not all_segments:
                self.log("No segments found.")
                return

            # Configuration
            config = self.project.config or {}

            # Filter out comment segments unless explicitly included
            segments = [
                seg for seg in all_segments
                if config.get("include_comments_in_workflows") or (seg.metadata_json or {}).get("type") != "comment"
            ]
            if not segments:
                self.log("No segments to process (all comments excluded).")
                return

            total_segments = len(segments)
            self.log(f"Generating drafts for {total_segments} segments...")

            self.update_progress(0, status="processing")

            manager = RAGManager(self.project_id, self.db)

            # Batch Processing - Group by CONTIGUOUS segments first
            # This ensures isolated segments get their own batch with proper context.
            BATCH_SIZE = 10
            success_count = 0
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")
            model_name = ai_settings.get("workflow_model")
            
            # Group segments into contiguous runs based on index
            contiguous_runs = []
            current_run = []
            
            for seg in segments:
                if not current_run:
                    current_run.append(seg)
                elif seg.index == current_run[-1].index + 1:
                    current_run.append(seg)
                else:
                    contiguous_runs.append(current_run)
                    current_run = [seg]
            
            if current_run:
                contiguous_runs.append(current_run)
            
            self.log(f"Found {len(contiguous_runs)} contiguous segment groups")
            
            # Build batches from contiguous runs
            all_batches = []
            for run in contiguous_runs:
                for i in range(0, len(run), BATCH_SIZE):
                    batch = run[i : i + BATCH_SIZE]
                    all_batches.append([s.id for s in batch])
            
            total_batches = len(all_batches)
            self.log(f"Split into {total_batches} batches for processing")

            for batch_idx, batch_ids in enumerate(all_batches):
                self.log(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch_ids)} segments)...")
                
                try:
                    # Async Call - unpack Usage
                    results, batch_usage = await manager.generate_batch_draft(
                        segment_ids=batch_ids,
                        source_lang=self.project.source_lang,
                        target_lang=self.project.target_lang,
                        model_name=model_name, 
                        custom_prompt=custom_prompt
                    )
                    
                    # Debug: Log batch usage
                    self.log(f"Batch usage: in={batch_usage.get('input_tokens', 0)}, out={batch_usage.get('output_tokens', 0)}")
                    
                    # Log Batch Usage (LLM) - Always log to AiUsageLog for auditing
                    input_tokens = batch_usage.get("input_tokens", 0)
                    output_tokens = batch_usage.get("output_tokens", 0)
                    
                    if input_tokens > 0 or output_tokens > 0:
                        first_id_in_batch = batch_ids[0]
                        self.db.add(AiUsageLog(
                            project_id=self.project_id,
                            segment_id=first_id_in_batch,
                            model=model_name or get_default_model_id(),
                            trigger_type="batch_generation",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens
                        ))
                        
                        # Update Project Stats - refresh config to avoid overwriting
                        self.db.refresh(self.project)
                        current_config = dict(self.project.config or {})
                        usage_stats = current_config.get("usage_stats", {})
                        model_key = model_name or get_default_model_id()
                        m_stats = usage_stats.get(model_key, {"input_tokens": 0, "output_tokens": 0})
                        m_stats["input_tokens"] += input_tokens
                        m_stats["output_tokens"] += output_tokens
                        usage_stats[model_key] = m_stats
                        current_config["usage_stats"] = usage_stats
                        self.project.config = current_config
                        flag_modified(self.project, "config")
                        
                        # Commit immediately to persist stats
                        self.db.commit()
                        self.log(f"Updated usage_stats: {model_key} -> in={m_stats['input_tokens']}, out={m_stats['output_tokens']}")

                    
                    for seg_id, result in results.items():
                        if result.error:
                            continue
                            
                        seg = next((s for s in segments if s.id == seg_id), None)
                        if seg:
                            meta = seg.metadata_json or {}
                            meta['ai_draft'] = result.target_text
                            
                            # Insert MT Result as a "Hit" and Context Matches
                            matches = []
                            if result.context_used:
                                matches = result.context_used.matches or []
                                gloss = result.context_used.glossary_hits or []
                                serialized_ctx = [m.model_dump() for m in matches] + [m.model_dump() for m in gloss]
                                
                                # Insert MT Result as a "Hit"
                                mt_hit = {
                                    "id": f"mt-result-{seg.id}",
                                    "content": result.target_text,
                                    "source_text": seg.source_content,
                                    "type": "mt",
                                    "category": "ai",
                                    "score": 100,
                                    "filename": "Machine Translation"
                                }
                                serialized_ctx.insert(0, mt_hit)
                                
                                meta['context_matches'] = serialized_ctx
                                
                                # Log Retrieval Usage (Per Segment)
                                r_usage = result.retrieval_usage or {}
                                if r_usage:
                                    for r_model, r_tokens in r_usage.items():
                                        if r_tokens > 0:
                                             self.db.add(AiUsageLog(
                                                project_id=self.project_id,
                                                segment_id=seg.id,
                                                model=r_model,
                                                trigger_type="retrieval",
                                                input_tokens=r_tokens,
                                                output_tokens=0
                                            ))
                                            # Update Stats (Retrieve)
                                             curr_conf = dict(self.project.config or {})
                                             u_stats = curr_conf.get("usage_stats", {})
                                             rm_stats = u_stats.get(r_model, {"input_tokens": 0, "output_tokens": 0})
                                             rm_stats["input_tokens"] += r_tokens
                                             u_stats[r_model] = rm_stats
                                             curr_conf["usage_stats"] = u_stats
                                             self.project.config = curr_conf
                                             flag_modified(self.project, "config")
                                
                            seg.metadata_json = dict(meta)
                            flag_modified(seg, "metadata_json")
                            success_count += 1
                            
                    self.db.commit()
                    
                    # Update Progress - based on batches completed
                    progress = int(((batch_idx + 1) / total_batches) * 100)
                    self.update_progress(progress, status="processing")
                    
                except Exception as e:
                     self.log(f"Batch {batch_idx + 1}/{total_batches} failed: {e}")
                     import traceback
                     print(traceback.format_exc())

            self.update_progress(100, status="ready")
            self.log(f"Batch Draft Complete. Updated metadata for {success_count} segments.")
            
        except Exception as e:
            self.fail(e)
