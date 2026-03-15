import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment, AiUsageLog
from ..rag.manager import RAGManager
from ..database import SessionLocal
from .base import BaseWorkflow
from ..config import get_default_model_id
from ..rag.inference import QuotaExceededError

from typing import List, Optional

async def run_background_batch_translate(project_id: str, segment_ids: Optional[List[str]] = None):
    """
    Entry point for BackgroundTasks. Must be async to run on the main event loop.
    Manages its own DB session.
    """
    db = SessionLocal()
    try:
        wf = BatchTranslateWorkflow(db, project_id)
        await wf.run(segment_ids)
    except Exception as e:
        print(f"Batch Translate Failed: {e}")
    finally:
        db.close()

class BatchTranslateWorkflow(BaseWorkflow):
    async def run(self, segment_ids: Optional[List[str]] = None):
        try:
            # Read mode from workflow config (set by process_batch_translation)
            config = self.project.config or {}
            wf_config = config.get("workflow", {})
            active_mode = wf_config.get("active_mode", "draft")
            is_analyze = (active_mode == "analyze")

            mode_label = "Pre-Analysis" if is_analyze else "Batch Translation"
            self.log(f"Starting {mode_label} (Async)...")

            # Fetch segments
            query = self.db.query(Segment).filter(Segment.project_id == self.project_id)
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))

            # Order by index for consistent processing
            all_segments = query.order_by(Segment.index).all()
            if not all_segments:
                self.log("No segments found.")
                return

            # Filter out locked/skipped segments
            segments = []
            seen_sources = set()  # Deduplicate: only translate each unique source once
            dedup_skipped = 0
            for seg in all_segments:
                inner = (seg.metadata_json or {}).get("metadata", {})
                if inner.get("locked") or inner.get("propagation_lock") or inner.get("skip"):
                    continue
                # Skip comment segments unless explicitly included
                if not config.get("include_comments_in_workflows") and (seg.metadata_json or {}).get("type") == "comment":
                    continue
                if not is_analyze and seg.source_content in seen_sources:
                    dedup_skipped += 1
                    continue
                seen_sources.add(seg.source_content)
                segments.append(seg)

            total_segments = len(segments)
            if dedup_skipped:
                self.log(f"Skipped {dedup_skipped} duplicate segments (will be propagated)")
            self.log(f"Processing {total_segments} segments...")

            self.update_progress(0, status="processing")

            # Init Manager
            manager = RAGManager(self.project_id, self.db)

            # Prompt Config
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")
            wf_types = config.get("workflow_types", {})
            model_name = ai_settings.get("workflow_model")

            # Batch Processing - Group by CONTIGUOUS segments first
            # This ensures isolated segments (e.g., segment 11 surrounded by translated segments)
            # get their own batch with proper context, rather than being mixed with distant segments.
            # Analyze mode uses larger batches since no LLM inference is needed.
            BATCH_SIZE = 20 if is_analyze else 5
            success_count = 0
            
            # Group segments into contiguous runs based on index
            # A "run" is a sequence of segments where each segment's index = previous + 1
            contiguous_runs = []
            current_run = []
            
            for seg in segments:
                if not current_run:
                    current_run.append(seg)
                elif seg.index == current_run[-1].index + 1:
                    # Contiguous with previous segment
                    current_run.append(seg)
                else:
                    # Gap detected - start new run
                    contiguous_runs.append(current_run)
                    current_run = [seg]
            
            # Don't forget the last run
            if current_run:
                contiguous_runs.append(current_run)
            
            self.log(f"Found {len(contiguous_runs)} contiguous segment groups")
            
            # Build batches from contiguous runs, respecting BATCH_SIZE
            all_batches = []
            for run in contiguous_runs:
                # Chunk each contiguous run by BATCH_SIZE
                for i in range(0, len(run), BATCH_SIZE):
                    batch = run[i : i + BATCH_SIZE]
                    all_batches.append([s.id for s in batch])
            
            total_batches = len(all_batches)
            self.log(f"Split into {total_batches} batches for processing")
            
            for batch_idx, batch_ids in enumerate(all_batches):
                # Check for cancellation before each batch
                if self.is_cancelled():
                    self.log(f"Workflow cancelled after {batch_idx}/{total_batches} batches ({success_count} segments translated).")
                    return

                self.log(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch_ids)} segments)...")
                
                try:
                    # Async Call - awaited directly on the main loop
                    # NOW UNPACKS Usage
                    results, batch_usage = await manager.generate_batch_draft(
                        segment_ids=batch_ids,
                        source_lang=self.project.source_lang,
                        target_lang=self.project.target_lang,
                        model_name=model_name,
                        custom_prompt=custom_prompt,
                        skip_ai=is_analyze
                    )
                    
                    # Debug: Log batch usage
                    self.log(f"Batch usage: in={batch_usage.get('input_tokens', 0)}, out={batch_usage.get('output_tokens', 0)}")
                    
                    # Log Batch Usage (LLM) - Always log to AiUsageLog for auditing
                    input_tokens = batch_usage.get("input_tokens", 0)
                    output_tokens = batch_usage.get("output_tokens", 0)
                    
                    if input_tokens > 0 or output_tokens > 0:
                        # Log to FIRST segment in batch for tracking
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
                        # Re-fetch from DB to get latest state
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
                        
                        # Commit immediately to persist stats before processing results
                        self.db.commit()
                        self.log(f"Updated usage_stats: {model_key} -> in={m_stats['input_tokens']}, out={m_stats['output_tokens']}")


                    # Process Results
                    if not results:
                        self.log(f"Batch {i//BATCH_SIZE + 1} returned no results.")
                    
                    for seg_id, result in results.items():
                        if result.error:
                            self.log(f"Segment {seg_id} failed: {result.error}")
                            continue

                        # Find segment (already attached to session)
                        seg = next((s for s in segments if s.id == seg_id), None)
                        if seg:
                            meta = seg.metadata_json or {}

                            if not is_analyze:
                                # 1. Update Target Content logic: Only if empty
                                updated_target = False
                                if not seg.target_content:
                                    seg.target_content = result.target_text
                                    seg.status = "mt_draft"
                                    updated_target = True

                                # 2. Update Metadata
                                meta['ai_draft'] = result.target_text

                            # 3. Context Matches & Glossary (always saved)
                            if result.context_used:
                                matches = result.context_used.matches or []
                                gloss = result.context_used.glossary_hits or []
                                serialized_ctx = [m.model_dump() for m in matches] + [m.model_dump() for m in gloss]

                                # Insert MT Result as a "Hit"
                                # For translate/draft: use the new AI result
                                # For analyze: reuse existing target_content as MT tile (no LLM cost)
                                mt_text = result.target_text if not is_analyze else seg.target_content
                                if mt_text:
                                    mt_hit = {
                                        "id": f"mt-result-{seg.id}",
                                        "content": mt_text,
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
                                    # We can log this per segment
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

                    # Propagate translations to repetitions
                    if not is_analyze:
                        propagated = 0
                        for seg_id, result in results.items():
                            if result.error or not result.target_text:
                                continue
                            seg = next((s for s in segments if s.id == seg_id), None)
                            if not seg:
                                continue
                            reps = self.db.query(Segment).filter(
                                Segment.project_id == self.project_id,
                                Segment.source_content == seg.source_content,
                                Segment.id != seg.id
                            ).all()
                            for rep in reps:
                                rep_meta = rep.metadata_json or {}
                                rep_inner = rep_meta.get("metadata", {})
                                if rep_inner.get("locked") or rep_inner.get("skip") or rep_inner.get("propagation_excluded"):
                                    continue
                                if rep.target_content:
                                    continue  # Don't overwrite existing translations
                                rep.target_content = result.target_text
                                rep.status = "mt_draft"
                                if "metadata" not in rep_meta:
                                    rep_meta["metadata"] = {}
                                rep_meta["metadata"]["propagation_lock"] = True
                                rep_meta["metadata"].pop("locked", None)
                                rep_meta["ai_draft"] = result.target_text
                                # Copy context matches
                                seg_meta = seg.metadata_json or {}
                                if seg_meta.get("context_matches"):
                                    rep_meta["context_matches"] = seg_meta["context_matches"]
                                rep.metadata_json = rep_meta
                                flag_modified(rep, "metadata_json")
                                propagated += 1
                        if propagated > 0:
                            self.db.commit()
                            self.log(f"Propagated {propagated} repetition(s)")

                    # Update Progress - based on batches completed
                    progress = int(((batch_idx + 1) / total_batches) * 100)
                    self.update_progress(progress, status="processing")

                except QuotaExceededError as qe:
                    self.log(f"API quota exceeded — stopping workflow. {success_count} segments translated before quota hit.")
                    self.fail(qe)
                    return
                except Exception as e:
                    self.log(f"Batch {batch_idx + 1}/{total_batches} failed with exception: {str(e)}")
                    import traceback
                    print(traceback.format_exc())

            self.update_progress(100, status="ready")
            if is_analyze:
                self.log(f"Pre-Analysis Complete. Processed {total_segments} segments.")
            else:
                self.log(f"Batch Translation Complete. Updated {success_count} segments.")

        except Exception as e:
            self.fail(e)
