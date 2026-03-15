import asyncio
import logging
from sqlalchemy.orm.attributes import flag_modified
from ..models import Project, Segment, AiUsageLog
from ..rag.manager import RAGManager
from ..database import SessionLocal
from .base import BaseWorkflow
from ..config import get_default_model_id
from ..rag.inference import QuotaExceededError
from ..services.auto_glossary import AutoGlossaryService, hash_content

from typing import List, Optional


async def run_background_sequential_translate(project_id: str, segment_ids: Optional[List[str]] = None):
    """
    Entry point for BackgroundTasks. Manages its own DB session.
    """
    db = SessionLocal()
    try:
        wf = SequentialTranslateWorkflow(db, project_id)
        await wf.run(segment_ids)
    except Exception as e:
        print(f"Sequential Translate Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


class SequentialTranslateWorkflow(BaseWorkflow):
    async def run(self, segment_ids: Optional[List[str]] = None):
        try:
            self.log("Starting Sequential Translation (1-by-1 with Auto-Glossary)...")

            # Fetch segments — only empty/draft, sorted by index
            query = self.db.query(Segment).filter(
                Segment.project_id == self.project_id
            )
            if segment_ids:
                query = query.filter(Segment.id.in_(segment_ids))
            else:
                # Only translate segments without target content
                query = query.filter(
                    (Segment.target_content == None) | (Segment.target_content == "")
                )

            segments = query.order_by(Segment.index).all()
            if not segments:
                self.log("No segments to translate.")
                return

            total = len(segments)
            self.log(f"Translating {total} segments sequentially...")
            self.update_progress(0, status="processing")

            # Load project config
            config = self.project.config or {}
            ai_settings = config.get("ai_settings", {})
            custom_prompt = ai_settings.get("custom_prompt", "Translate the following text accurately.")
            model_name = ai_settings.get("workflow_model")
            glossary_model = ai_settings.get("glossary_model") or model_name
            topic = ai_settings.get("topic_description", "")

            success_count = 0
            propagated_count = 0
            skipped_ids = set()  # Track segments already handled via propagation

            for idx, seg in enumerate(segments):
                # Check for cancellation before each segment
                if self.is_cancelled():
                    self.log(f"Workflow cancelled after {success_count}/{total} segments.")
                    return

                # Skip locked, skipped, or already-propagated segments
                inner_meta = (seg.metadata_json or {}).get("metadata", {})
                if inner_meta.get("locked") or inner_meta.get("propagation_lock") or inner_meta.get("skip") or seg.id in skipped_ids:
                    self.log(f"Segment {idx+1}/{total} (#{seg.index+1}) — skipped (locked/propagated)")
                    continue

                # Skip comment segments unless explicitly included
                if not config.get("include_comments_in_workflows") and (seg.metadata_json or {}).get("type") == "comment":
                    self.log(f"Segment {idx+1}/{total} (#{seg.index+1}) — skipped (comment)")
                    continue

                try:
                    self.log(f"Segment {idx+1}/{total} (#{seg.index+1})...")

                    target_text = None
                    result = None
                    for attempt in range(2):  # 1 attempt + 1 retry
                        # Fresh RAGManager per attempt (picks up new auto-glossary entries)
                        manager = RAGManager(self.project_id, self.db)

                        result = await manager.generate_draft(
                            segment=seg,
                            source_lang=self.project.source_lang,
                            target_lang=self.project.target_lang,
                            model_name=model_name,
                            custom_prompt=custom_prompt,
                        )

                        if result.error:
                            if attempt == 0:
                                self.log(f"Segment {seg.index}: Error — {result.error} (retrying...)")
                                continue
                            self.log(f"Segment {seg.index}: Error after retry — {result.error}")
                            break

                        target_text = (result.target_text or "").strip()
                        if target_text:
                            break
                        if attempt == 0:
                            self.log(f"Segment {seg.index}: Empty AI response (retrying...)")

                    if not target_text:
                        self.log(f"Segment {seg.index}: No valid response after retry — skipped")
                        continue

                    # 3. Save: target_content, status=mt_draft
                    seg.target_content = target_text
                    seg.status = "mt_draft"

                    # 4. Update metadata (ai_draft, context_matches)
                    meta = seg.metadata_json or {}
                    meta["ai_draft"] = target_text

                    if result.context_used:
                        matches = result.context_used.matches or []
                        gloss = result.context_used.glossary_hits or []
                        serialized_ctx = [m.model_dump() for m in matches] + [m.model_dump() for m in gloss]

                        # Insert MT result as a hit
                        mt_hit = {
                            "id": f"mt-result-{seg.id}",
                            "content": target_text,
                            "source_text": seg.source_content,
                            "type": "mt",
                            "category": "ai",
                            "score": 100,
                            "filename": "Machine Translation",
                        }
                        serialized_ctx.insert(0, mt_hit)
                        meta["context_matches"] = serialized_ctx

                    seg.metadata_json = dict(meta)
                    flag_modified(seg, "metadata_json")

                    # Log usage
                    r_usage = result.retrieval_usage or {}
                    usage = result.usage or {}
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)

                    if input_tokens > 0 or output_tokens > 0:
                        self.db.add(AiUsageLog(
                            project_id=self.project_id,
                            segment_id=seg.id,
                            model=model_name or get_default_model_id(),
                            trigger_type="sequential_translate",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        ))

                    # Commit translation before auto-glossary extraction
                    self.db.commit()
                    success_count += 1

                    # 4b. Propagate to repetitions (same source_content)
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
                        rep.target_content = result.target_text
                        rep.status = "mt_draft"
                        if "metadata" not in rep_meta:
                            rep_meta["metadata"] = {}
                        rep_meta["metadata"]["propagation_lock"] = True
                        rep_meta["metadata"].pop("locked", None)
                        rep_meta["ai_draft"] = result.target_text
                        # Copy context matches if available
                        if meta.get("context_matches"):
                            rep_meta["context_matches"] = meta["context_matches"]
                        rep.metadata_json = rep_meta
                        flag_modified(rep, "metadata_json")
                        skipped_ids.add(rep.id)
                        prop_count += 1
                    if prop_count > 0:
                        self.db.commit()
                        propagated_count += prop_count
                        self.log(f"Segment {seg.index}: propagated to {prop_count} repetition(s)")

                    # 5. Auto-Glossary extraction (after commit so data is persisted)
                    try:
                        glossary_svc = AutoGlossaryService(self.project_id, self.db)
                        new_entries, gloss_usage = await glossary_svc.extract_and_store(
                            segment_id=seg.id,
                            source_text=seg.source_content,
                            target_text=result.target_text,
                            topic=topic,
                            source_lang=self.project.source_lang,
                            target_lang=self.project.target_lang,
                            model_name=glossary_model,
                        )
                        if new_entries:
                            self.log(f"Segment {seg.index}: +{len(new_entries)} auto-glossary terms")
                        if gloss_usage and gloss_usage.get("input_tokens"):
                            self.db.add(AiUsageLog(
                                project_id=self.project_id,
                                segment_id=seg.id,
                                model=gloss_usage["model"],
                                trigger_type="auto_glossary",
                                input_tokens=gloss_usage["input_tokens"],
                                output_tokens=gloss_usage["output_tokens"],
                            ))
                            # Update project usage_stats
                            self.db.refresh(self.project)
                            current_config = dict(self.project.config or {})
                            u_stats = current_config.get("usage_stats", {})
                            g_model = gloss_usage["model"]
                            g_m_stats = u_stats.get(g_model, {"input_tokens": 0, "output_tokens": 0})
                            g_m_stats["input_tokens"] += gloss_usage["input_tokens"]
                            g_m_stats["output_tokens"] += gloss_usage["output_tokens"]
                            u_stats[g_model] = g_m_stats
                            current_config["usage_stats"] = u_stats
                            self.project.config = current_config
                            flag_modified(self.project, "config")
                            self.db.commit()
                    except Exception as gloss_err:
                        self.log(f"Segment {seg.index}: Auto-glossary failed — {gloss_err}")

                    # 6. Set auto_glossary_hash in metadata (tracks content version)
                    meta = seg.metadata_json or {}
                    if "metadata" not in meta:
                        meta["metadata"] = {}
                    meta["metadata"]["auto_glossary_hash"] = hash_content(result.target_text)
                    seg.metadata_json = dict(meta)
                    flag_modified(seg, "metadata_json")
                    self.db.commit()

                    # 7. Progress
                    progress = int(((idx + 1) / total) * 100)
                    self.update_progress(progress, status="processing")

                except QuotaExceededError as qe:
                    self.log(f"API quota exceeded — stopping workflow. {success_count}/{total} segments translated before quota hit.")
                    self.fail(qe)
                    return
                except Exception as seg_err:
                    self.log(f"Segment {seg.index}: Failed — {seg_err}")
                    import traceback
                    print(traceback.format_exc())

            self.update_progress(100, status="ready")
            self.log(f"Sequential Translation Complete. {success_count} translated, {propagated_count} propagated (of {total} total).")

        except Exception as e:
            self.fail(e)
