import os
import json
import datetime as dt_module
from collections import defaultdict, deque
from typing import Optional, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from ..models import Project, Segment, ProjectFile, ProjectFileCategory, AiUsageLog
from ..storage import download_file
from ..document.parser import parse_document
from ..rag.retrieval import RetrievalEngine
from .base import BaseWorkflow
from ..database import SessionLocal

UPLOAD_DIR = "uploads"
BACKUP_DIR = os.path.join(UPLOAD_DIR, "backups")

def run_background_vector_regen(project_id: str):
    """
    Background Task Entrypoint.
    Creates a new session for the workflow to run safely in background.
    """
    db = SessionLocal()
    try:
        wf = ReinitializeWorkflow(db, project_id)
        wf.embed_segments()
    except Exception as e:
        # Fallback logging if workflow init failed
        print(f"Background Vector Regen Failed: {e}")
    finally:
        db.close()

class ReinitializeWorkflow(BaseWorkflow):
    def run(self, new_file_upload: Optional[Any] = None) -> Project:
        """
        Main entry point for Reinitialization.
        Re-parses ALL source files, merges with existing translations per-file,
        and replaces segments. Backs up translated segments before delete.
        Optionally accepts a new file to replace the first source file.
        """

        if not self.project:
            raise HTTPException(status_code=404, detail="Project not found")

        # 1. Find ALL source files (ordered by upload time for stable indexing)
        source_records = self.db.query(ProjectFile).filter(
            ProjectFile.project_id == self.project_id,
            ProjectFile.category == ProjectFileCategory.source.value
        ).order_by(ProjectFile.uploaded_at).all()

        if not source_records and not new_file_upload:
            raise HTTPException(status_code=400, detail="No source file found to reinitialize.")

        # 1.5. Replace first source file if a new upload is provided
        if new_file_upload and source_records:
            try:
                first_record = source_records[0]
                content = new_file_upload.file.read()
                with open(first_record.file_path, "wb") as f:
                    f.write(content)

                first_record.filename = new_file_upload.filename
                first_record.uploaded_at = datetime.utcnow()
                self.db.add(first_record)
                self.db.commit()
                self.log(f"Replaced source file with {new_file_upload.filename}")

            except Exception as e:
                self.fail(e)
                raise HTTPException(status_code=500, detail=f"Failed to save new source file: {e}")

        # 2. Parse ALL source files fresh
        from ..document.parsing_service import process_file_parsing

        all_parsed = []  # List of (file_record, parsed_segments) tuples
        for source_record in source_records:
            try:
                segments_internal = process_file_parsing(
                    file_path_or_url=source_record.file_path,
                    project_id=self.project_id,
                    source_lang=self.project.source_lang,
                    original_filename=source_record.filename
                )
                all_parsed.append((source_record, segments_internal))
                self.log(f"Parsed {len(segments_internal)} segments from {source_record.filename}")
            except Exception as e:
                self.fail(e)
                raise HTTPException(status_code=500, detail=f"Parsing failed for {source_record.filename}: {e}")

        # 3. Backup existing segments (before any delete)
        self._backup_segments()

        # 4. Per-file merge: match old translations within same file only
        old_segments = self.db.query(Segment).filter(
            Segment.project_id == self.project_id
        ).order_by(Segment.index).all()

        final_db_segments = self._merge_per_file(all_parsed, old_segments)

        # 5. Atomic Replace
        try:
            # Unlink AI Usage Logs
            self.db.query(AiUsageLog).filter(
                AiUsageLog.project_id == self.project_id
            ).update({AiUsageLog.segment_id: None}, synchronize_session=False)

            # Delete old
            self.db.query(Segment).filter(Segment.project_id == self.project_id).delete()

            # Insert new
            self.db.add_all(final_db_segments)

            # Set Status for Next Step (Vector Gen)
            self.project.rag_status = "ingesting"
            self.project.rag_progress = 0
            self.log("Reinitialization successful. Starting vector regeneration...")

            self.db.commit()
            self.db.refresh(self.project)

            return self.project

        except Exception as e:
            self.db.rollback()
            self.fail(e)
            raise HTTPException(status_code=500, detail=f"Database update failed: {e}")

    def _backup_segments(self):
        """
        Backs up all segments with translations to a JSON file before reinitialize.
        Only segments that have target_content are worth backing up.
        """
        translated_segments = self.db.query(Segment).filter(
            Segment.project_id == self.project_id,
            Segment.target_content.isnot(None),
            Segment.target_content != ""
        ).order_by(Segment.index).all()

        if not translated_segments:
            self.log("No translated segments to backup.")
            return

        backup_data = {
            "project_id": self.project_id,
            "project_name": self.project.name or self.project.filename,
            "timestamp": datetime.utcnow().isoformat(),
            "segment_count": len(translated_segments),
            "segments": [
                {
                    "id": seg.id,
                    "file_id": seg.file_id,
                    "index": seg.index,
                    "source_content": seg.source_content,
                    "target_content": seg.target_content,
                    "status": seg.status,
                }
                for seg in translated_segments
            ]
        }

        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"reinit_backup_{self.project_id}_{timestamp}.json")

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        self.log(f"Backed up {len(translated_segments)} translated segments to {backup_path}")

    def _merge_per_file(self, all_parsed, old_segments):
        """
        Per-file merge: matches old translations with new segments WITHIN the same file.
        Prevents cross-file translation stealing.
        Segments with file_id=NULL (orphans from legacy) are used as a fallback pool.
        """
        # Build per-file old-segment maps + orphan pool
        file_maps = {}      # file_id -> {source_content -> deque(old_seg)}
        orphan_map = defaultdict(deque)  # source_content -> deque(old_seg) for file_id=NULL

        for seg in old_segments:
            # Normalize key: strip whitespace so that segments parsed with old
            # whitespace-inside-tags behaviour still match after the fix.
            key = (seg.source_content or "").strip()
            if seg.file_id:
                if seg.file_id not in file_maps:
                    file_maps[seg.file_id] = defaultdict(deque)
                file_maps[seg.file_id][key].append(seg)
            else:
                orphan_map[key].append(seg)

        self.log(f"Old segments: {len(old_segments)} total, {sum(len(q) for q in orphan_map.values())} orphaned (no file_id).")

        final_db_segments = []
        global_index = 0
        total_preserved = 0
        total_new = 0

        for source_record, new_segs in all_parsed:
            file_old_map = file_maps.get(source_record.id, defaultdict(deque))
            file_preserved = 0
            file_new = 0

            for new_seg_int in new_segs:
                target_content = None
                status = "draft"

                # 1st priority: match within same file
                lookup_key = (new_seg_int.source_text or "").strip()
                old_match = None
                if file_old_map[lookup_key]:
                    old_match = file_old_map[lookup_key].popleft()
                    target_content = old_match.target_content
                    status = old_match.status
                    file_preserved += 1
                # 2nd priority: match from orphan pool (legacy segments without file_id)
                elif orphan_map[lookup_key]:
                    old_match = orphan_map[lookup_key].popleft()
                    target_content = old_match.target_content
                    status = old_match.status
                    file_preserved += 1
                else:
                    file_new += 1

                seg_dump = new_seg_int.model_dump()

                # Preserve cached AI/context data from old segment
                if old_match and old_match.metadata_json:
                    old_meta = old_match.metadata_json
                    for key in ('context_matches', 'ai_draft'):
                        if key in old_meta:
                            seg_dump[key] = old_meta[key]

                new_db_seg = Segment(
                    id=new_seg_int.segment_id,
                    project_id=self.project_id,
                    file_id=source_record.id,
                    index=global_index,
                    source_content=new_seg_int.source_text,
                    target_content=target_content,
                    status=status,
                    metadata_json=seg_dump
                )
                final_db_segments.append(new_db_seg)
                global_index += 1

            total_preserved += file_preserved
            total_new += file_new
            self.log(f"  {source_record.filename}: {file_preserved} preserved, {file_new} new")

        self.log(f"Reinit Merge Total: {total_preserved} preserved, {total_new} new. {len(final_db_segments)} segments.")
        return final_db_segments

    def embed_segments(self):
        """
        Background Task Logic.
        Regenerates vectors for all segments.
        """
        try:
            self.log("Starting Segment Vector Regeneration...")

            engine = RetrievalEngine()
            if not engine._client:
                 self.log("Error: Voyage AI not loaded.")
                 self.project.rag_status = "error"
                 self.db.commit()
                 return

            segments = self.db.query(Segment).filter(Segment.project_id == self.project_id).all()
            total = len(segments)
            BATCH_SIZE = 32
            processed = 0

            total_tokens = 0

            for i in range(0, total, BATCH_SIZE):
                batch_segs = segments[i : i+BATCH_SIZE]
                texts = [engine.clean_tags(s.source_content) for s in batch_segs]

                try:
                    embeddings, tokens = engine.embed_batch(texts, input_type="document")
                    total_tokens += tokens

                    for s, vec in zip(batch_segs, embeddings):
                        s.embedding = vec

                    self.db.commit()

                    processed += len(batch_segs)
                    progress = int((processed / total) * 100)
                    self.update_progress(progress)

                except Exception as e:
                    self.log(f"Embedding error batch {i}: {e}")

            # Update Usage Stats
            if total_tokens > 0:
                current_config = dict(self.project.config or {})
                usage_stats = current_config.get("usage_stats", {})
                m_stats = usage_stats.get("voyage-3-large", {"input_tokens": 0, "output_tokens": 0})

                m_stats["input_tokens"] += total_tokens

                usage_stats["voyage-3-large"] = m_stats
                current_config["usage_stats"] = usage_stats
                self.project.config = current_config
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(self.project, "config")
                self.db.commit()

            self.update_progress(100, status="ready")
            self.log(f"Segment vectors updated successfully. ({total_tokens} tokens)")

        except Exception as e:
            self.fail(e)
