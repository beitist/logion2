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
from ..utils.tc_diff import (
    generate_tc_markup,
    convert_ai_tc_to_tiptap,
    extract_clean_from_tc,
    validate_ai_tc_markup,
    accumulate_tc_stages,
)
from .base import BaseWorkflow
from ..config import get_default_model_id

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

            # ── 1. Fetch all segments ──────────────────────────────
            query = self.db.query(Segment).filter(
                Segment.project_id == self.project_id
            )
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))

            all_segments = query.order_by(Segment.index).all()

            # Separate TC segments (revision_stages ≥ 2) from regular ones
            tc_segments = []
            regular_segments = []
            for seg in all_segments:
                meta = (seg.metadata_json or {}).get("metadata", {})
                stages = meta.get("revision_stages", [])
                if len(stages) >= 2:
                    tc_segments.append((seg, stages))
                else:
                    regular_segments.append(seg)

            if not tc_segments and not regular_segments:
                self.log("No segments found.")
                self.update_progress(100, status="ready")
                return

            # ── Determine mode ────────────────────────────────────
            config = self.project.config or {}
            tc_settings = config.get("tc_settings", {})
            tc_mode = tc_settings.get("tc_mode", "first_last")
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")
            model_name = ai_settings.get("workflow_model")

            self.log(f"Mode: {tc_mode} — Found {len(tc_segments)} TC + {len(regular_segments)} regular segments.")
            self.update_progress(0, status="processing")

            if tc_mode == "step_by_step":
                await self._run_step_by_step(tc_segments, model_name, custom_prompt, regular_segments)
            else:
                await self._run_first_last(tc_segments, model_name, custom_prompt, regular_segments)

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
    def _apply_regular(regular_segments, all_t) -> int:
        """Apply translations to regular (non-TC) segments. Returns success count."""
        count = 0
        for seg in regular_segments:
            t = all_t.get(f"{seg.id}__regular", "")
            if not t:
                continue
            seg.target_content = t
            seg.status = "mt_draft"
            count += 1
        return count

    @staticmethod
    def _build_tm_chain(seg_state: dict, level: int) -> list:
        """
        Build TM matches for a given level from the full chain history.
        Includes all previous source→translation pairs, newest first
        with highest score so the MT prioritises the most recent revision.

        Uses 'clean_translations' if available (step_by_step mode),
        falls back to 'translations' (first_last mode).
        """
        tm = []
        base_idx = seg_state["base_idx"]
        translations = seg_state.get("clean_translations") or seg_state.get("translations", {})
        # Walk from the level just before down to base
        for prev_level in range(level - 1, base_idx - 1, -1):
            prev_t = translations.get(str(prev_level), "")
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

    _TC_MARKUP_ADDENDUM = (
        "\n\nTRACK CHANGES MODE:\n"
        "A reference translation is provided as the highest-scoring TM match. "
        "The source text was revised compared to the reference source. "
        "Update the reference translation to reflect the source changes, "
        "marking ALL changes with inline tags:\n"
        "- <ins>new text</ins> for inserted/added text\n"
        "- <del>old text</del> for deleted/removed text\n"
        "- Text that did not change MUST remain exactly as-is (no tags).\n\n"
        "If a word was replaced: <del>old word</del> <ins>new word</ins>\n"
        "If text was added: existing text <ins>added text</ins>\n"
        "If text was removed: <del>removed text</del> remaining text\n"
        "If nothing changed: return the reference translation unchanged (no tags).\n\n"
        "CRITICAL: Only mark actual differences. Keep unchanged parts identical to the reference.\n"
        "If the source change is only a spelling/punctuation fix with no semantic impact, "
        "return the reference translation EXACTLY unchanged (no tags)."
    )

    # ──────────────────────────────────────────────────────────────
    # MODE: first_last — translate stage 0, revise for final, diff
    # ──────────────────────────────────────────────────────────────
    async def _run_first_last(self, tc_segments, model_name, custom_prompt, regular_segments=None):
        orchestrator = InferenceOrchestrator()
        simple, proper = self._categorize(tc_segments)
        regular_segments = regular_segments or []

        # Filter regular segments: skip already translated / locked / empty source
        regular_to_translate = [
            seg for seg in regular_segments
            if seg.source_content and seg.source_content.strip()
            and not (seg.target_content and seg.target_content.strip())
        ]

        self.log(f"  Batch (insert/delete): {len(simple)}, Chain (revisions): {len(proper)}, Regular: {len(regular_to_translate)}")

        # ── Phase 1: Batch translate simple + base (stage 0) for proper + regular ──
        batch_items = []

        # Regular (non-TC) segments — simple MT
        for seg in regular_to_translate:
            batch_items.append({
                "id": f"{seg.id}__regular",
                "source_text": seg.source_content,
                "tm_matches": [], "glossary_matches": [],
            })

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
        regular_count = self._apply_regular(regular_to_translate, all_t)
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
        self.log(f"TC Batch (first_last) Complete. {regular_count} regular + {simple_count} simple + {tc_count} TC.")

    # ──────────────────────────────────────────────────────────────
    # MODE: step_by_step — translate base, chain stage-by-stage,
    #   store per-stage translations + precomputed TC markup
    # ──────────────────────────────────────────────────────────────
    async def _run_step_by_step(self, tc_segments, model_name, custom_prompt, regular_segments=None):
        orchestrator = InferenceOrchestrator()
        simple, proper = self._categorize(tc_segments)
        regular_segments = regular_segments or []

        # Filter regular segments: skip already translated / locked / empty source
        regular_to_translate = [
            seg for seg in regular_segments
            if seg.source_content and seg.source_content.strip()
            and not (seg.target_content and seg.target_content.strip())
        ]

        self.log(f"  Batch (insert/delete): {len(simple)}, Chain (revisions): {len(proper)}, Regular: {len(regular_to_translate)}")

        # ── Phase 1: Batch translate simple + base stages + regular ─────────
        batch_items = []

        # Regular (non-TC) segments — simple MT
        for seg in regular_to_translate:
            batch_items.append({
                "id": f"{seg.id}__regular",
                "source_text": seg.source_content,
                "tm_matches": [], "glossary_matches": [],
            })

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

        # Apply simple + regular results immediately
        simple_count = self._apply_simple(simple, all_t)
        regular_count = self._apply_regular(regular_to_translate, all_t)

        self.update_progress(30, status="processing")

        if not proper:
            self.db.commit()
            self.update_progress(100, status="ready")
            self.log(f"TC Batch (step_by_step) Complete. {regular_count} regular + {simple_count} simple segments.")
            return

        # ── Phase 2+: Chain through stages level-by-level ─────────
        # AI generates TC markup directly (<ins>/<del>) instead of
        # producing clean translations that get word-level-diffed.
        # We extract clean text from AI output for chaining to next stage.
        tc_markup_prompt = custom_prompt + self._TC_MARKUP_ADDENDUM

        max_depth = max(len(stages) for _, stages in proper)

        # Per-segment state for chaining
        # clean_translations: clean text for TM chaining (no markup)
        # raw_outputs: AI output with <ins>/<del> tags per level
        seg_state = {}
        for seg, stages in proper:
            base_idx = 1 if not stages[0]["text"].strip() else 0
            base_t = all_t.get(f"{seg.id}__base", "")
            seg_state[seg.id] = {
                "segment": seg, "stages": stages,
                "base_idx": base_idx,
                "clean_translations": {str(base_idx): base_t},
                "raw_outputs": {},
            }

        for level in range(1, max_depth):
            level_items = []

            for sid, st in seg_state.items():
                if level <= st["base_idx"] or level >= len(st["stages"]):
                    continue
                text = st["stages"][level]["text"]
                prev_clean = st["clean_translations"].get(str(level - 1), "")
                if not text.strip() or not prev_clean:
                    continue

                # TM chain uses CLEAN translations (no markup)
                tm = self._build_tm_chain(st, level)
                level_items.append({
                    "id": f"{sid}__s{level}",
                    "source_text": text,
                    "tm_matches": tm,
                    "glossary_matches": [],
                })

            if not level_items:
                continue

            self.log(f"Stage {level}: Revising {len(level_items)} segments (AI TC markup)...")
            level_t = await self._translate_batch(
                orchestrator, level_items, model_name, tc_markup_prompt
            )

            # Extract clean text for chaining; store raw for markup conversion
            for sid, st in seg_state.items():
                raw = level_t.get(f"{sid}__s{level}", "")
                if not raw:
                    continue
                st["raw_outputs"][str(level)] = raw
                st["clean_translations"][str(level)] = extract_clean_from_tc(raw)

            progress = int(30 + (level / max(max_depth - 1, 1)) * 60)
            self.update_progress(min(progress, 95), status="processing")

        # ── Store results ─────────────────────────────────────────
        # target_content = accumulated TC document (all stages' marks layered).
        # Per-stage TC markup (from AI or word-level fallback) stored in
        # metadata for the slider UI.
        tc_settings = (self.project.config or {}).get("tc_settings", {})
        replace_authors = tc_settings.get("tc_replace_authors", False)
        translator_name = tc_settings.get("tc_translator_name") or "Translator"
        tc_count = 0
        fallback_count = 0

        for sid, st in seg_state.items():
            seg = st["segment"]
            stages = st["stages"]
            base_idx = st["base_idx"]
            base_t = st["clean_translations"].get(str(base_idx), "")
            if not base_t:
                continue

            final_clean = st["clean_translations"].get(str(len(stages) - 1), "")

            # Build per-stage TC markup, clean translations, and author info
            tc_stage_markup = {}
            stage_translations = dict(st["clean_translations"])
            ordered_clean_texts = []
            ordered_authors = []

            for lvl in range(base_idx + 1, len(stages)):
                prev_clean = st["clean_translations"].get(str(lvl - 1), "")
                curr_clean = st["clean_translations"].get(str(lvl), "")
                raw = st["raw_outputs"].get(str(lvl), "")

                if not prev_clean or not curr_clean:
                    continue

                # Author info for this stage
                if replace_authors:
                    a_name = translator_name
                    a_id = translator_name.lower().replace(" ", "_") + f"__stage_{lvl}"
                    a_date = ""
                else:
                    stage_info = stages[lvl]
                    a_name = stage_info.get("author") or "Editor"
                    a_id = (stage_info.get("author") or "editor").lower().replace(" ", "_") + f"__stage_{lvl}"
                    a_date = stage_info.get("date") or ""

                # Collect for accumulation
                ordered_clean_texts.append(curr_clean)
                ordered_authors.append((a_id, a_name, a_date))

                # Per-stage markup for slider UI
                if prev_clean == curr_clean:
                    tc_stage_markup[str(lvl)] = curr_clean
                elif raw and validate_ai_tc_markup(raw) and ('<ins>' in raw or '<del>' in raw):
                    tc_stage_markup[str(lvl)] = convert_ai_tc_to_tiptap(
                        raw, author_id=a_id, author_name=a_name, date=a_date
                    )
                else:
                    if raw and not validate_ai_tc_markup(raw):
                        logger.warning(f"Malformed AI TC markup for segment {sid} stage {lvl}, falling back to word-level diff")
                    tc_stage_markup[str(lvl)] = generate_tc_markup(
                        old_text=prev_clean, new_text=curr_clean,
                        author_id=a_id, author_name=a_name, date=a_date,
                    )
                    fallback_count += 1

            # target_content = accumulated multi-author TC document
            if ordered_clean_texts and base_t != (final_clean or base_t):
                seg.target_content = accumulate_tc_stages(
                    base_t, ordered_clean_texts, ordered_authors
                )
            else:
                seg.target_content = final_clean or base_t
            seg.status = "mt_draft"

            meta = seg.metadata_json or {}
            inner = meta.get("metadata", {})
            inner["stage_translations"] = stage_translations
            inner["tc_stage_markup"] = tc_stage_markup
            inner["tc_base_translation"] = base_t
            inner["tc_final_translation"] = final_clean or base_t
            meta["metadata"] = inner
            seg.metadata_json = dict(meta)
            flag_modified(seg, "metadata_json")
            tc_count += 1

        self.db.commit()
        self.update_progress(100, status="ready")
        fb_note = f" ({fallback_count} word-level fallbacks)" if fallback_count else ""
        self.log(f"TC Batch (step_by_step) Complete. {regular_count} regular + {simple_count} simple + {tc_count} TC{fb_note}.")

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
                model=model_name or get_default_model_id(),
                trigger_type="tc_batch",
                input_tokens=total_usage["input_tokens"],
                output_tokens=total_usage["output_tokens"],
            ))

            self.db.refresh(self.project)
            current_config = dict(self.project.config or {})
            usage_stats = current_config.get("usage_stats", {})
            model_key = model_name or get_default_model_id()
            m_stats = usage_stats.get(model_key, {"input_tokens": 0, "output_tokens": 0})
            m_stats["input_tokens"] += total_usage["input_tokens"]
            m_stats["output_tokens"] += total_usage["output_tokens"]
            usage_stats[model_key] = m_stats
            current_config["usage_stats"] = usage_stats
            self.project.config = current_config
            flag_modified(self.project, "config")
            self.db.commit()

        return all_translations
