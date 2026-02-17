"""
TC Batch Workflow — Langchain-style MT for Track Changes segments.

Segments are categorised first:
- Simple (insert-only with 2 stages, or deleted-final): batched fast, no TC markup.
- Proper TC (actual revisions between stages): processed stage-by-stage
  with chained TM references (all previous source→translation pairs).
  The revision prompt instructs the MT to minimize changes; a word-level
  diff then converts consecutive translations into TC markup.

Supports two output modes (project config tc_settings.tc_mode):

- first_last (default): target_content = TC markup (base vs final diff).
- step_by_step: target_content = clean base translation,
  per-stage TC markup stored in metadata.stage_translations / tc_stage_markup
  for the slider UI.

The resulting target_content is parseable by tiptap's
track-change-extension (InsertionMark / DeletionMark).
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

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

    # ──────────────────────────────────────────────────────────────
    # Main entry
    # ──────────────────────────────────────────────────────────────
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
    # Shared: categorize TC segments
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _categorize(tc_segments):
        """
        Split TC segments into two buckets:
        - simple: insert-only (2 stages) or deleted-final → batch-translate, no TC markup
        - proper: actual revisions between stages → need langchain (chain) approach
        """
        simple, proper = [], []
        for seg, stages in tc_segments:
            is_insert_only = not stages[0]["text"].strip()
            is_deleted_final = not stages[-1]["text"].strip()
            is_simple = (is_insert_only and len(stages) == 2) or is_deleted_final
            if is_simple:
                simple.append((seg, stages))
            else:
                proper.append((seg, stages))
        return simple, proper

    @staticmethod
    def _apply_simple(simple, all_t) -> int:
        """Apply translations to simple segments. Returns success count."""
        count = 0
        for seg, stages in simple:
            t = all_t.get(f"{seg.id}__simple", "")
            if not t:
                continue
            seg.target_content = t
            seg.status = "mt_draft"
            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["tc_base_translation"] = t
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")
            count += 1
        return count

    @staticmethod
    def _build_tm_chain(seg_state: dict, level: int) -> list:
        """
        Build TM matches for a given level from the full chain history.
        Includes all previous source→translation pairs, newest first
        with highest score so the MT prioritises the most recent revision.
        """
        tm = []
        base_idx = seg_state["base_idx"]
        # Walk from the level just before down to base
        for prev_level in range(level - 1, base_idx - 1, -1):
            prev_t = seg_state["translations"].get(str(prev_level), "")
            prev_source = seg_state["stages"][prev_level]["text"]
            if prev_t and prev_source.strip():
                # Most recent revision gets highest score
                distance = level - prev_level
                score = max(99 - (distance - 1) * 5, 70)
                tm.append({
                    "source": prev_source,
                    "target": prev_t,
                    "score": score,
                })
        return tm

    _REVISION_ADDENDUM = (
        "\n\nIMPORTANT: A reference translation is provided as TM match. "
        "The source text was revised compared to the reference source. "
        "Update the reference translation to reflect the source changes only. "
        "Keep wording identical where the source has not changed."
    )

    # ──────────────────────────────────────────────────────────────
    # MODE: first_last — translate stage 0, revise for final, diff
    # ──────────────────────────────────────────────────────────────
    async def _run_first_last(self, tc_segments, model_name, custom_prompt):
        orchestrator = InferenceOrchestrator()
        simple, proper = self._categorize(tc_segments)

        self.log(f"  Batch (insert/delete): {len(simple)}, Chain (revisions): {len(proper)}")

        # ── Phase 1: Batch translate simple + base (stage 0) for proper ──
        batch_items = []

        for seg, stages in simple:
            idx = 1 if not stages[0]["text"].strip() else 0
            if stages[idx]["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__simple",
                    "source_text": stages[idx]["text"],
                    "tm_matches": [], "glossary_matches": [],
                })

        for seg, stages in proper:
            base_idx = 1 if not stages[0]["text"].strip() else 0
            if stages[base_idx]["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__s0",
                    "source_text": stages[base_idx]["text"],
                    "tm_matches": [], "glossary_matches": [],
                })

        all_t = await self._translate_batch(
            orchestrator, batch_items, model_name, custom_prompt
        ) if batch_items else {}

        self.update_progress(40, status="processing")

        # ── Phase 2: Chain through intermediate stages to final ──────
        # For segments with >2 stages, we chain through each level so
        # the MT accumulates context. For 2-stage proper segments, this
        # is just one revision call (base → final).
        revision_prompt = custom_prompt + self._REVISION_ADDENDUM

        # Build per-segment state
        seg_state = {}
        for seg, stages in proper:
            base_idx = 1 if not stages[0]["text"].strip() else 0
            base_t = all_t.get(f"{seg.id}__s0", "")
            seg_state[seg.id] = {
                "segment": seg, "stages": stages,
                "base_idx": base_idx,
                "translations": {str(base_idx): base_t},
            }

        max_depth = max(len(stages) for _, stages in proper) if proper else 0

        for level in range(1, max_depth):
            level_items = []

            for sid, st in seg_state.items():
                if level <= st["base_idx"] or level >= len(st["stages"]):
                    continue
                text = st["stages"][level]["text"]
                prev_t = st["translations"].get(str(level - 1), "")
                if not text.strip() or not prev_t:
                    continue

                tm = self._build_tm_chain(st, level)
                level_items.append({
                    "id": f"{sid}__s{level}",
                    "source_text": text,
                    "tm_matches": tm,
                    "glossary_matches": [],
                })

            if not level_items:
                continue

            self.log(f"Chain level {level}: Revising {len(level_items)} segments...")
            level_t = await self._translate_batch(
                orchestrator, level_items, model_name, revision_prompt
            )

            for sid, st in seg_state.items():
                t = level_t.get(f"{sid}__s{level}", "")
                if t:
                    st["translations"][str(level)] = t

            progress = int(40 + (level / max(max_depth - 1, 1)) * 40)
            self.update_progress(min(progress, 85), status="processing")

        self.update_progress(85, status="processing")

        # ── Apply results ──
        self.log("Generating TC markup...")
        simple_count = self._apply_simple(simple, all_t)
        tc_count = 0

        # Author/date settings
        tc_settings = (self.project.config or {}).get("tc_settings", {})
        replace_authors = tc_settings.get("tc_replace_authors", False)
        translator_name = tc_settings.get("tc_translator_name") or "Translator"

        for sid, st in seg_state.items():
            seg = st["segment"]
            stages = st["stages"]
            base_idx = st["base_idx"]
            base_t = st["translations"].get(str(base_idx), "")
            final_idx = len(stages) - 1
            final_t = st["translations"].get(str(final_idx), "")

            if not base_t and not final_t:
                continue

            if not base_t or not final_t or base_t == final_t:
                seg.target_content = final_t or base_t
            else:
                if replace_authors:
                    a_name = translator_name
                    a_id = translator_name.lower().replace(" ", "_") + f"__stage_{final_idx}"
                    a_date = ""  # → _format_tc_date falls back to utcnow()
                else:
                    author_info = stages[-1]
                    a_name = author_info.get("author") or "Editor"
                    a_id = (author_info.get("author") or "editor").lower().replace(" ", "_") + f"__stage_{final_idx}"
                    a_date = author_info.get("date") or ""
                seg.target_content = generate_tc_markup(
                    old_text=base_t, new_text=final_t,
                    author_id=a_id,
                    author_name=a_name,
                    date=a_date,
                )
            seg.status = "mt_draft"

            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["tc_base_translation"] = base_t
            inner["tc_final_translation"] = final_t
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")
            tc_count += 1

        self.db.commit()
        self.update_progress(100, status="ready")
        self.log(f"TC Batch (first_last) Complete. {simple_count} simple + {tc_count} TC / {len(tc_segments)} total.")

    # ──────────────────────────────────────────────────────────────
    # MODE: step_by_step — translate base, chain stage-by-stage,
    #   store per-stage translations + precomputed TC markup
    # ──────────────────────────────────────────────────────────────
    async def _run_step_by_step(self, tc_segments, model_name, custom_prompt):
        orchestrator = InferenceOrchestrator()
        simple, proper = self._categorize(tc_segments)

        self.log(f"  Batch (insert/delete): {len(simple)}, Chain (revisions): {len(proper)}")

        # ── Phase 1: Batch translate simple + base stages ─────────
        batch_items = []

        for seg, stages in simple:
            idx = 1 if not stages[0]["text"].strip() else 0
            if stages[idx]["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__simple",
                    "source_text": stages[idx]["text"],
                    "tm_matches": [], "glossary_matches": [],
                })

        for seg, stages in proper:
            base_idx = 1 if not stages[0]["text"].strip() else 0
            if stages[base_idx]["text"].strip():
                batch_items.append({
                    "id": f"{seg.id}__base",
                    "source_text": stages[base_idx]["text"],
                    "tm_matches": [], "glossary_matches": [],
                })

        all_t = await self._translate_batch(
            orchestrator, batch_items, model_name, custom_prompt
        ) if batch_items else {}

        # Apply simple results immediately
        simple_count = self._apply_simple(simple, all_t)

        self.update_progress(30, status="processing")

        if not proper:
            self.db.commit()
            self.update_progress(100, status="ready")
            self.log(f"TC Batch (step_by_step) Complete. {simple_count} simple segments.")
            return

        # ── Phase 2+: Chain through stages level-by-level ─────────
        # Each level includes ALL previous source→translation pairs as
        # TM references so the MT revises with full context of the edit history.
        revision_prompt = custom_prompt + self._REVISION_ADDENDUM

        max_depth = max(len(stages) for _, stages in proper)

        # Per-segment state for chaining
        seg_state = {}
        for seg, stages in proper:
            base_idx = 1 if not stages[0]["text"].strip() else 0
            base_t = all_t.get(f"{seg.id}__base", "")
            seg_state[seg.id] = {
                "segment": seg, "stages": stages,
                "base_idx": base_idx,
                "translations": {str(base_idx): base_t},
            }

        for level in range(1, max_depth):
            level_items = []

            for sid, st in seg_state.items():
                if level <= st["base_idx"] or level >= len(st["stages"]):
                    continue
                text = st["stages"][level]["text"]
                prev_t = st["translations"].get(str(level - 1), "")
                if not text.strip() or not prev_t:
                    continue

                # Full TM chain: all previous source→translation pairs
                tm = self._build_tm_chain(st, level)
                level_items.append({
                    "id": f"{sid}__s{level}",
                    "source_text": text,
                    "tm_matches": tm,
                    "glossary_matches": [],
                })

            if not level_items:
                continue

            self.log(f"Stage {level}: Revising {len(level_items)} segments...")
            level_t = await self._translate_batch(
                orchestrator, level_items, model_name, revision_prompt
            )

            for sid, st in seg_state.items():
                t = level_t.get(f"{sid}__s{level}", "")
                if t:
                    st["translations"][str(level)] = t

            progress = int(30 + (level / max(max_depth - 1, 1)) * 60)
            self.update_progress(min(progress, 95), status="processing")

        # ── Store results ─────────────────────────────────────────
        # For each segment: target_content = clean base translation,
        # metadata stores per-stage clean translations AND precomputed
        # TC markup (diff between consecutive stages) for the slider UI.
        tc_settings = (self.project.config or {}).get("tc_settings", {})
        replace_authors = tc_settings.get("tc_replace_authors", False)
        translator_name = tc_settings.get("tc_translator_name") or "Translator"
        tc_count = 0
        for sid, st in seg_state.items():
            seg = st["segment"]
            stages = st["stages"]
            base_idx = st["base_idx"]
            base_t = st["translations"].get(str(base_idx), "")
            if not base_t:
                continue

            # target_content = clean base translation (user starts at base stage)
            seg.target_content = base_t
            seg.status = "mt_draft"

            final_t = st["translations"].get(str(len(stages) - 1), "")

            # Precompute TC markup for each stage transition
            tc_stage_markup = {}
            for lvl in range(base_idx + 1, len(stages)):
                prev_t = st["translations"].get(str(lvl - 1), "")
                curr_t = st["translations"].get(str(lvl), "")
                if not prev_t or not curr_t:
                    continue
                if prev_t == curr_t:
                    tc_stage_markup[str(lvl)] = curr_t
                else:
                    if replace_authors:
                        a_name = translator_name
                        a_id = translator_name.lower().replace(" ", "_") + f"__stage_{lvl}"
                        a_date = ""
                    else:
                        stage_info = stages[lvl]
                        a_name = stage_info.get("author") or "Editor"
                        a_id = (stage_info.get("author") or "editor").lower().replace(" ", "_") + f"__stage_{lvl}"
                        a_date = stage_info.get("date") or ""
                    tc_stage_markup[str(lvl)] = generate_tc_markup(
                        old_text=prev_t, new_text=curr_t,
                        author_id=a_id,
                        author_name=a_name,
                        date=a_date,
                    )

            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["stage_translations"] = st["translations"]
            inner["tc_stage_markup"] = tc_stage_markup
            inner["tc_base_translation"] = base_t
            inner["tc_final_translation"] = final_t or base_t
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")
            tc_count += 1

        self.db.commit()
        self.update_progress(100, status="ready")
        self.log(f"TC Batch (step_by_step) Complete. {simple_count} simple + {tc_count} TC segments.")

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
