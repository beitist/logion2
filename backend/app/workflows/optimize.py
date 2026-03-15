import re
import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment, AiUsageLog
from ..database import SessionLocal
from .base import BaseWorkflow
from ..config import get_default_model_id
from ..rag.inference import InferenceOrchestrator, QuotaExceededError
from ..rag.manager import RAGManager
from ..routers.chat import _build_chat_system_prompt

from typing import List, Optional

TAG_PATTERN = re.compile(r'</?(\d+)>')
# Segments that are only numbers, punctuation, whitespace (and tags) — no translatable text
NON_TEXT_PATTERN = re.compile(r'^[\d\s\.\,\;\:\!\?\-\–\—\(\)\[\]\{\}\/\\%\$€£¥#\*\+\=\@\&\|\"\'°±×÷<>]+$')

DEFAULT_OPTIMIZE_PROMPT = (
    "Optimiere die folgende Übersetzung. "
    "Antworte AUSSCHLIESSLICH mit dem optimierten Satz. "
    "Keine Erklärungen, keine Anführungszeichen, keine Einleitungen, "
    "keine Alternativen — nur der eine beste Satz."
)


async def run_background_optimize(project_id: str, segment_ids: Optional[List[str]] = None):
    """Entry point for BackgroundTasks. Manages its own DB session."""
    db = SessionLocal()
    try:
        wf = OptimizeWorkflow(db, project_id)
        await wf.run(segment_ids)
    except Exception as e:
        print(f"Optimize Workflow Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


class OptimizeWorkflow(BaseWorkflow):
    async def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log("Starting Optimize Workflow...")

            # Fetch segments with existing translations
            query = self.db.query(Segment).filter(
                Segment.project_id == self.project_id,
                Segment.target_content != None,
                Segment.target_content != "",
            )
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))

            segments = query.order_by(Segment.index).all()
            if not segments:
                self.log("No segments to optimize.")
                return

            total = len(segments)
            self.log(f"Optimizing {total} segments...")
            self.update_progress(0, status="processing")

            # Load config
            config = self.project.config or {}
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "")
            chat_model = ai_settings.get("model") or get_default_model_id()
            tagging_model = ai_settings.get("glossary_model") or ai_settings.get("workflow_model") or chat_model
            optimize_prompt = ai_settings.get("optimize_prompt") or DEFAULT_OPTIMIZE_PROMPT

            orchestrator = InferenceOrchestrator()
            success_count = 0
            tagged_count = 0
            propagated_count = 0
            skipped_ids = set()

            for idx, seg in enumerate(segments):
                if self.is_cancelled():
                    self.log(f"Workflow cancelled after {success_count}/{total} segments.")
                    return

                # Skip locked, skipped, or already-propagated segments
                inner_meta = (seg.metadata_json or {}).get("metadata", {})
                if inner_meta.get("locked") or inner_meta.get("propagation_lock") or inner_meta.get("skip") or seg.id in skipped_ids:
                    continue

                # Skip comment segments unless explicitly included
                if not config.get("include_comments_in_workflows") and (seg.metadata_json or {}).get("type") == "comment":
                    continue

                # Skip non-text segments (only numbers, punctuation, whitespace)
                stripped = TAG_PATTERN.sub('', seg.source_content or '').strip()
                if not stripped or NON_TEXT_PATTERN.match(stripped):
                    continue

                try:
                    self.log(f"Segment {idx+1}/{total} (#{seg.index+1})...")

                    # 1. Find preceding segment (always include for reading flow context)
                    preceding_segment = None
                    if seg.index is not None and seg.index > 0:
                        preceding_segment = self.db.query(Segment).filter(
                            Segment.project_id == self.project_id,
                            Segment.index == seg.index - 1
                        ).first()

                    # 2. Fresh RAG lookup — ensures TM + glossary context is up-to-date
                    #    Merges with existing context_matches, preserving the MT card
                    try:
                        manager = RAGManager(self.project_id, self.db)
                        loop = asyncio.get_event_loop()
                        ctx = await loop.run_in_executor(None, lambda: manager.assembler.assemble_context(seg))
                        if ctx:
                            matches = ctx.matches or []
                            gloss = ctx.glossary_hits or []
                            fresh = [m.model_dump() for m in matches] + [m.model_dump() for m in gloss]
                            meta = seg.metadata_json or {}
                            existing = meta.get("context_matches", [])
                            # Preserve MT card from previous translation
                            mt_cards = [m for m in existing if m.get("type") == "mt"]
                            # Fresh results replace non-MT matches only
                            merged = mt_cards + fresh
                            meta["context_matches"] = merged
                            seg.metadata_json = dict(meta)
                            flag_modified(seg, "metadata_json")
                    except Exception as rag_err:
                        self.log(f"Segment {seg.index}: RAG lookup failed ({rag_err}) — using existing context")

                    # 3. Build system prompt (same as chat, now with fresh context)
                    system_prompt = _build_chat_system_prompt(seg, self.project, custom_prompt, preceding_segment)

                    # 4. Optimize call (chat model for quality)
                    messages = [{"role": "user", "content": optimize_prompt}]
                    reply_text, usage = await orchestrator.call_chat(system_prompt, messages, chat_model)

                    # Strip any accidental quotes or whitespace from reply
                    reply_text = reply_text.strip().strip('"').strip("'").strip("\u201e").strip("\u201c").strip()

                    if not reply_text:
                        self.log(f"Segment {seg.index}: Empty response — skipped")
                        continue

                    # 5. Tag re-injection if source has tags
                    has_tags = bool(TAG_PATTERN.search(seg.source_content or ""))
                    final_text = reply_text

                    if has_tags:
                        try:
                            tagged_text = await self._reinject_tags(
                                orchestrator, tagging_model,
                                seg.source_content, reply_text
                            )
                            if tagged_text:
                                final_text = tagged_text
                                tagged_count += 1
                        except Exception as tag_err:
                            self.log(f"Segment {seg.index}: Tagging failed ({tag_err}) — using tag-free version")

                    # 6. Save optimized translation (keep current status)
                    seg.target_content = final_text
                    # Don't change status — already translated

                    # 7. Log usage
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    if input_tokens > 0 or output_tokens > 0:
                        self.db.add(AiUsageLog(
                            project_id=self.project_id,
                            segment_id=seg.id,
                            model=chat_model,
                            trigger_type="optimize",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        ))

                        # Update project usage_stats
                        self.db.refresh(self.project)
                        current_config = dict(self.project.config or {})
                        u_stats = current_config.get("usage_stats", {})
                        m_stats = u_stats.get(chat_model, {"input_tokens": 0, "output_tokens": 0})
                        m_stats["input_tokens"] += input_tokens
                        m_stats["output_tokens"] += output_tokens
                        u_stats[chat_model] = m_stats
                        current_config["usage_stats"] = u_stats
                        self.project.config = current_config
                        flag_modified(self.project, "config")

                    self.db.commit()
                    success_count += 1

                    # 8. Propagate to repetitions
                    repetitions = self.db.query(Segment).filter(
                        Segment.project_id == self.project_id,
                        Segment.source_content == seg.source_content,
                        Segment.id != seg.id
                    ).all()
                    prop_count = 0
                    for rep in repetitions:
                        rep_meta = rep.metadata_json or {}
                        rep_inner = rep_meta.get("metadata", {})
                        if rep_inner.get("locked") or rep_inner.get("skip") or rep_inner.get("propagation_excluded"):
                            continue
                        rep.target_content = final_text
                        if "metadata" not in rep_meta:
                            rep_meta["metadata"] = {}
                        rep_meta["metadata"]["propagation_lock"] = True
                        rep_meta["metadata"].pop("locked", None)
                        rep.metadata_json = rep_meta
                        flag_modified(rep, "metadata_json")
                        skipped_ids.add(rep.id)
                        prop_count += 1
                    if prop_count > 0:
                        self.db.commit()
                        propagated_count += prop_count

                    # 9. Progress
                    progress = int(((idx + 1) / total) * 100)
                    self.update_progress(progress, status="processing")

                except QuotaExceededError as qe:
                    self.log(f"API quota exceeded — stopping. {success_count}/{total} segments optimized.")
                    self.fail(qe)
                    return
                except Exception as seg_err:
                    self.log(f"Segment {seg.index}: Failed — {seg_err}")
                    import traceback
                    print(traceback.format_exc())

            self.update_progress(100, status="ready")
            self.log(
                f"Optimize Complete. {success_count} optimized, "
                f"{tagged_count} re-tagged, {propagated_count} propagated "
                f"(of {total} total)."
            )

        except Exception as e:
            self.fail(e)

    async def _reinject_tags(
        self, orchestrator: InferenceOrchestrator, model: str,
        source_with_tags: str, translation_without_tags: str
    ) -> str | None:
        """Use a cheap LLM call to re-inject XML tags from source into the translation."""
        # Extract expected tag IDs from source
        expected_tags = set(TAG_PATTERN.findall(source_with_tags))

        system = (
            "You are a tag injection assistant. Your job is to insert XML-like formatting tags "
            "from a source sentence into its translation at the correct positions.\n"
            "Tags look like <1>, </1>, <2>, </2> etc. They mark formatting spans.\n"
            "Rules:\n"
            "- Preserve the exact translation wording — do NOT change, rewrite, or translate anything.\n"
            "- Insert each opening and closing tag at the position that corresponds to the source.\n"
            "- Return ONLY the tagged translation, nothing else."
        )
        user_msg = (
            f"Source (with tags): {source_with_tags}\n"
            f"Translation (without tags): {translation_without_tags}\n\n"
            f"Return the translation with tags inserted:"
        )

        reply, usage = await orchestrator.call_chat(system, [{"role": "user", "content": user_msg}], model)

        # Log tagging usage
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if input_tokens > 0 or output_tokens > 0:
            self.db.add(AiUsageLog(
                project_id=self.project_id,
                segment_id=None,
                model=model,
                trigger_type="optimize_tagging",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ))
            # Update stats for tagging model
            self.db.refresh(self.project)
            current_config = dict(self.project.config or {})
            u_stats = current_config.get("usage_stats", {})
            m_stats = u_stats.get(model, {"input_tokens": 0, "output_tokens": 0})
            m_stats["input_tokens"] += input_tokens
            m_stats["output_tokens"] += output_tokens
            u_stats[model] = m_stats
            current_config["usage_stats"] = u_stats
            self.project.config = current_config
            flag_modified(self.project, "config")

        reply = reply.strip()

        # Validate: result must contain the expected tags
        result_tags = set(TAG_PATTERN.findall(reply))
        if not expected_tags.issubset(result_tags):
            return None  # Tagging failed — missing tags

        return reply
