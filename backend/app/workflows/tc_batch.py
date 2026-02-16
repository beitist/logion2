"""
TC Batch Workflow — Step-by-step MT for Track Changes segments.

Supports two modes (from project config tc_settings.tc_mode):

- first_last (default): Translate stage 0 and final stage, diff → single-author TC markup.
- step_by_step: Translate ALL stages independently, store stage 0 as base target_content,
  store all per-stage translations in metadata.stage_translations for manual review.

The resulting target_content is parseable by tiptap's
track-change-extension (InsertionMark / DeletionMark).
"""

import asyncio
import logging
from typing import List, Optional

from sqlalchemy.orm.attributes import flag_modified

from ..models import Project, Segment, AiUsageLog
from ..rag.inference import InferenceOrchestrator
from ..database import SessionLocal
from ..utils.tc_diff import generate_tc_markup
from .base import BaseWorkflow

logger = logging.getLogger("TCBatch")


async def run_background_tc_batch(project_id: str, segment_ids: Optional[List[str]] = None):
    """Entry point for BackgroundTasks."""
    db = SessionLocal()
    try:
        wf = TCBatchWorkflow(db, project_id)
        await wf.run(segment_ids)
    except Exception as e:
        logger.error(f"TC Batch Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


class TCBatchWorkflow(BaseWorkflow):
    BATCH_SIZE = 10

    async def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log("Starting TC Batch Translation...")

            # ── 1. Fetch TC segments ──────────────────────────────
            query = self.db.query(Segment).filter(
                Segment.project_id == self.project_id
            )
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))

            all_segments = query.order_by(Segment.index).all()

            # Filter to only segments with revision_stages (≥ 2 stages)
            tc_segments = []
            for seg in all_segments:
                meta = (seg.metadata_json or {}).get("metadata", {})
                stages = meta.get("revision_stages", [])
                if len(stages) >= 2:
                    tc_segments.append((seg, stages))

            if not tc_segments:
                self.log("No TC segments with revision stages found.")
                self.update_progress(100, status="ready")
                return

            # ── Determine mode ────────────────────────────────────
            config = self.project.config or {}
            tc_settings = config.get("tc_settings", {})
            tc_mode = tc_settings.get("tc_mode", "first_last")
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")
            model_name = ai_settings.get("workflow_model")

            self.log(f"Mode: {tc_mode} — Found {len(tc_segments)} TC segments.")
            self.update_progress(0, status="processing")

            if tc_mode == "step_by_step":
                await self._run_step_by_step(tc_segments, model_name, custom_prompt)
            else:
                await self._run_first_last(tc_segments, model_name, custom_prompt)

        except Exception as e:
            self.fail(e)

    # ──────────────────────────────────────────────────────────────
    # MODE: first_last — translate stage 0 + final, single diff
    # ──────────────────────────────────────────────────────────────
    async def _run_first_last(self, tc_segments, model_name, custom_prompt):
        orchestrator = InferenceOrchestrator()

        # Build batch items: stage_0 and stage_final per segment
        batch_items = []
        task_map = {}

        for seg, stages in tc_segments:
            stage_0 = stages[0]
            stage_final = stages[-1]

            task_map[seg.id] = {
                "segment": seg,
                "stage_0": stage_0,
                "stage_final": stage_final,
            }

            # Only translate non-empty stages
            if stage_0["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__s0",
                    "source_text": stage_0["text"],
                    "tm_matches": [],
                    "glossary_matches": [],
                })
            if stage_final["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__final",
                    "source_text": stage_final["text"],
                    "tm_matches": [],
                    "glossary_matches": [],
                })

        # Translate in batches
        all_translations = await self._translate_batch(orchestrator, batch_items, model_name, custom_prompt)

        # Generate TC markup
        self.log("Generating TC markup from translation diffs...")
        success_count = 0

        for seg_id, task in task_map.items():
            seg = task["segment"]
            t0 = all_translations.get(f"{seg_id}__s0", "")
            tf = all_translations.get(f"{seg_id}__final", "")

            if not t0 and not tf:
                self.log(f"Segment {seg.index}: No translations received, skipping.")
                continue

            if t0 == tf:
                seg.target_content = tf or t0
                seg.status = "mt_draft"
            else:
                author_info = task["stage_final"]
                author_id = (author_info.get("author") or "editor").lower().replace(" ", "_")
                author_name = author_info.get("author") or "Editor"
                date = author_info.get("date") or ""

                tc_content = generate_tc_markup(
                    old_text=t0,
                    new_text=tf,
                    author_id=author_id,
                    author_name=author_name,
                    date=date,
                )
                seg.target_content = tc_content
                seg.status = "mt_draft"

            # Store translations in metadata
            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["tc_base_translation"] = t0
            inner["tc_final_translation"] = tf
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")

            success_count += 1

        self.db.commit()
        self.update_progress(100, status="ready")
        self.log(f"TC Batch (first_last) Complete. {success_count}/{len(tc_segments)} segments.")

    # ──────────────────────────────────────────────────────────────
    # MODE: step_by_step — translate ALL stages, store per-stage
    # ──────────────────────────────────────────────────────────────
    async def _run_step_by_step(self, tc_segments, model_name, custom_prompt):
        orchestrator = InferenceOrchestrator()

        # Build batch items for ALL non-empty stages
        batch_items = []
        task_map = {}  # seg_id → {segment, stages}

        for seg, stages in tc_segments:
            task_map[seg.id] = {"segment": seg, "stages": stages}

            for i, stage in enumerate(stages):
                if stage["text"].strip():
                    batch_items.append({
                        "id": f"{seg.id}__s{i}",
                        "source_text": stage["text"],
                        "tm_matches": [],
                        "glossary_matches": [],
                    })

        self.log(f"Translating {len(batch_items)} stage texts across {len(tc_segments)} segments...")

        # Translate in batches
        all_translations = await self._translate_batch(orchestrator, batch_items, model_name, custom_prompt)

        # Process results
        self.log("Storing per-stage translations...")
        success_count = 0

        for seg_id, task in task_map.items():
            seg = task["segment"]
            stages = task["stages"]

            # Collect translations for each stage
            stage_translations = {}
            for i, stage in enumerate(stages):
                key = f"{seg_id}__s{i}"
                translation = all_translations.get(key, "")
                if translation:
                    stage_translations[str(i)] = translation

            if not stage_translations:
                self.log(f"Segment {seg.index}: No translations received, skipping.")
                continue

            # Determine base stage (stage 1 for insert-only, else stage 0)
            is_insert_only = not stages[0]["text"].strip()
            base_idx = 1 if is_insert_only else 0
            base_translation = stage_translations.get(str(base_idx), "")

            # Store base translation as target_content (clean, no TC)
            if base_translation:
                seg.target_content = base_translation
                seg.status = "mt_draft"

            # Store all per-stage translations in metadata
            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["stage_translations"] = stage_translations
            inner["tc_base_translation"] = base_translation
            inner["tc_final_translation"] = stage_translations.get(str(len(stages) - 1), "")
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")

            success_count += 1

        self.db.commit()
        self.update_progress(100, status="ready")
        self.log(f"TC Batch (step_by_step) Complete. {success_count}/{len(tc_segments)} segments with per-stage translations.")

    # ──────────────────────────────────────────────────────────────
    # Shared: translate batch items in chunks
    # ──────────────────────────────────────────────────────────────
    async def _translate_batch(self, orchestrator, batch_items, model_name, custom_prompt):
        all_translations = {}
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        chunks = [
            batch_items[i:i + self.BATCH_SIZE]
            for i in range(0, len(batch_items), self.BATCH_SIZE)
        ]
        total_chunks = len(chunks)

        for chunk_idx, chunk in enumerate(chunks):
            self.log(f"Translating chunk {chunk_idx + 1}/{total_chunks} ({len(chunk)} items)...")

            try:
                translations, usage = await orchestrator.generate_structured_batch(
                    preceding_context=[],
                    following_context=[],
                    batch_items=chunk,
                    source_lang=self.project.source_lang,
                    target_lang=self.project.target_lang,
                    model_name=model_name,
                    custom_prompt=custom_prompt,
                )

                all_translations.update(translations)
                total_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_usage["output_tokens"] += usage.get("output_tokens", 0)

            except Exception as e:
                self.log(f"Chunk {chunk_idx + 1} failed: {e}")
                import traceback
                traceback.print_exc()

            progress = int(((chunk_idx + 1) / total_chunks) * 80)
            self.update_progress(progress, status="processing")

        # Log usage
        if total_usage["input_tokens"] > 0 or total_usage["output_tokens"] > 0:
            self.db.add(AiUsageLog(
                project_id=self.project_id,
                segment_id=None,
                model=model_name or "gemini-2.0-flash-001",
                trigger_type="tc_batch",
                input_tokens=total_usage["input_tokens"],
                output_tokens=total_usage["output_tokens"],
            ))

            self.db.refresh(self.project)
            current_config = dict(self.project.config or {})
            usage_stats = current_config.get("usage_stats", {})
            model_key = model_name or "gemini-2.0-flash-001"
            m_stats = usage_stats.get(model_key, {"input_tokens": 0, "output_tokens": 0})
            m_stats["input_tokens"] += total_usage["input_tokens"]
            m_stats["output_tokens"] += total_usage["output_tokens"]
            usage_stats[model_key] = m_stats
            current_config["usage_stats"] = usage_stats
            self.project.config = current_config
            flag_modified(self.project, "config")
            self.db.commit()

        return all_translations
