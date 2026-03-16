import io
import os
import json
import hashlib
import zipfile
import glob
import uuid
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func as sql_func

from ..models import (
    Project, ProjectFile, Segment, ContextChunk,
    TranslationUnit, GlossaryEntry, AiUsageLog,
)
from ..storage import get_file_url, upload_file
from ..core.config import settings as app_config

logger = logging.getLogger("BackupService")


def _serialize_datetime(dt):
    return dt.isoformat() if dt else None


def _serialize_embedding(emb):
    """Convert pgvector embedding to a list of floats (or None)."""
    if emb is None:
        return None
    return [float(v) for v in emb]


class BackupService:
    def __init__(self, db: Session):
        self.db = db

    # ── Export ──────────────────────────────────────────────────────

    def export_project_data(self, project_id: str) -> dict:
        """Serialize all project data to a dict (for backup.json)."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        files = self.db.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()
        segments = self.db.query(Segment).filter(Segment.project_id == project_id).order_by(Segment.index).all()
        glossary = self.db.query(GlossaryEntry).filter(GlossaryEntry.project_id == project_id).all()
        tus = self.db.query(TranslationUnit).filter(TranslationUnit.project_id == project_id).all()
        usage = self.db.query(AiUsageLog).filter(AiUsageLog.project_id == project_id).all()

        # Context chunks via files
        file_ids = [f.id for f in files]
        chunks = self.db.query(ContextChunk).filter(ContextChunk.file_id.in_(file_ids)).all() if file_ids else []

        return {
            "logion_version": app_config.PROJECT_VERSION,
            "backup_version": 1,
            "created_at": datetime.utcnow().isoformat(),
            "project": {
                "id": project.id,
                "filename": project.filename,
                "name": project.name,
                "status": project.status,
                "rag_status": project.rag_status,
                "created_at": _serialize_datetime(project.created_at),
                "source_lang": project.source_lang,
                "target_lang": project.target_lang,
                "use_clean_template": project.use_clean_template,
                "use_ai": project.use_ai,
                "file_hash": project.file_hash,
                "config": project.config,
                "ingestion_logs": project.ingestion_logs,
                "rag_progress": project.rag_progress,
                "archived": project.archived,
                "archive_folder": project.archive_folder,
            },
            "files": [{
                "id": f.id,
                "category": f.category,
                "filename": f.filename,
                "file_path": f.file_path,
                "uploaded_at": _serialize_datetime(f.uploaded_at),
            } for f in files],
            "segments": [{
                "id": s.id,
                "file_id": s.file_id,
                "index": s.index,
                "source_content": s.source_content,
                "target_content": s.target_content,
                "status": s.status,
                "metadata_json": s.metadata_json,
                "embedding": _serialize_embedding(s.embedding),
            } for s in segments],
            "glossary_entries": [{
                "id": e.id,
                "source_term": e.source_term,
                "target_term": e.target_term,
                "source_lemma": e.source_lemma,
                "context_note": e.context_note,
                "origin": e.origin,
                "segment_id": e.segment_id,
                "created_at": _serialize_datetime(e.created_at),
            } for e in glossary],
            "translation_units": [{
                "id": t.id,
                "source_hash": t.source_hash,
                "source_text": t.source_text,
                "target_text": t.target_text,
                "origin_type": t.origin_type,
                "context_prev": t.context_prev,
                "context_next": t.context_next,
                "created_at": _serialize_datetime(t.created_at),
                "changed_at": _serialize_datetime(t.changed_at),
                "creation_user": t.creation_user,
            } for t in tus],
            "context_chunks": [{
                "id": c.id,
                "file_id": c.file_id,
                "content": c.content,
                "rich_content": c.rich_content,
                "embedding": _serialize_embedding(c.embedding),
                "chunk_index": c.chunk_index,
                "source_segment": c.source_segment,
                "target_segment": c.target_segment,
                "alignment_score": c.alignment_score,
                "alignment_type": c.alignment_type,
            } for c in chunks],
            "ai_usage_logs": [{
                "id": u.id,
                "segment_id": u.segment_id,
                "timestamp": _serialize_datetime(u.timestamp),
                "model": u.model,
                "trigger_type": u.trigger_type,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
            } for u in usage],
        }

    def export_project_zip(self, project_id: str, include_files: bool = True) -> bytes:
        """Create a .logion.zip with backup.json + optional physical files."""
        data = self.export_project_data(project_id)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write backup.json
            zf.writestr("backup.json", json.dumps(data, ensure_ascii=False, indent=None))

            # Write physical files
            if include_files:
                for f_rec in data["files"]:
                    file_path = f_rec["file_path"]
                    abs_path = get_file_url(file_path)
                    if os.path.isfile(abs_path):
                        arc_name = f"files/{f_rec['category']}/{f_rec['filename']}"
                        zf.write(abs_path, arc_name)

        return buf.getvalue()

    # ── Content Hash (for skip-if-unchanged) ─────────────────────

    def _compute_content_hash(self, project_id: str) -> str:
        """Fast hash over segment count + statuses + target content.
        Changes when any segment is edited, added, or removed."""
        rows = (
            self.db.query(Segment.status, Segment.target_content)
            .filter(Segment.project_id == project_id)
            .order_by(Segment.index)
            .all()
        )
        h = hashlib.sha256()
        for status, target in rows:
            h.update((status or "").encode())
            h.update((target or "").encode())
        # Also include glossary count and TU count
        g_count = self.db.query(sql_func.count(GlossaryEntry.id)).filter(
            GlossaryEntry.project_id == project_id).scalar()
        tu_count = self.db.query(sql_func.count(TranslationUnit.id)).filter(
            TranslationUnit.project_id == project_id).scalar()
        h.update(f"g{g_count}t{tu_count}".encode())
        return h.hexdigest()[:16]

    def _read_last_backup_hash(self, backup_dir: str, short_id: str) -> str | None:
        """Read the content hash from the most recent backup's hash sidecar file."""
        pattern = os.path.join(backup_dir, f"*_{short_id}_*.logion.hash")
        existing = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if existing:
            try:
                return open(existing[0]).read().strip()
            except OSError:
                pass
        return None

    # ── Save to Disk ───────────────────────────────────────────────

    def save_backup_to_disk(
        self, project_id: str, backup_dir: str,
        max_count: int = 3, include_files: bool = True,
        skip_if_unchanged: bool = True
    ) -> str | None:
        """Write ZIP to backup_dir, rotate old backups. Returns the path, or None if skipped."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        short_id = project_id[:8]
        os.makedirs(backup_dir, exist_ok=True)

        # Skip if nothing changed since last backup
        if skip_if_unchanged:
            content_hash = self._compute_content_hash(project_id)
            last_hash = self._read_last_backup_hash(backup_dir, short_id)
            if content_hash == last_hash:
                logger.debug(f"Skipping backup for {project.name} — no changes")
                return None

        zip_bytes = self.export_project_zip(project_id, include_files)

        # Sanitize project name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in (project.name or "project")).strip().replace(" ", "_")[:40]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name}_{short_id}_{timestamp}.logion.zip"
        filepath = os.path.join(backup_dir, filename)

        with open(filepath, "wb") as f:
            f.write(zip_bytes)

        # Write hash sidecar
        hash_path = filepath.replace(".logion.zip", ".logion.hash")
        content_hash = content_hash if skip_if_unchanged else self._compute_content_hash(project_id)
        with open(hash_path, "w") as f:
            f.write(content_hash)

        logger.info(f"Backup saved: {filepath} ({len(zip_bytes)} bytes)")

        # Rotate — keep only the newest max_count backups for this project
        for ext in ("*.logion.zip", "*.logion.hash"):
            pattern = os.path.join(backup_dir, f"*_{short_id}_{ext}")
            existing = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            for old in existing[max_count:]:
                try:
                    os.remove(old)
                    logger.info(f"Rotated old backup: {old}")
                except OSError:
                    pass

        return filepath

    # ── List Backups ───────────────────────────────────────────────

    def list_backups(self, backup_dir: str) -> list:
        """Scan backup_dir for .logion.zip files and return metadata."""
        if not os.path.isdir(backup_dir):
            return []

        results = []
        for path in sorted(glob.glob(os.path.join(backup_dir, "*.logion.zip")), key=os.path.getmtime, reverse=True):
            try:
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
                # Read minimal metadata from backup.json inside zip
                meta = {"logion_version": "?", "project": {"name": "?"}}
                try:
                    with zipfile.ZipFile(path, "r") as zf:
                        with zf.open("backup.json") as bf:
                            # Read only first ~2KB to get the header fields
                            raw = bf.read(2048).decode("utf-8", errors="replace")
                            # Simple extraction — parse enough JSON for the header
                            partial = json.loads(raw + '}}]}]}]}]}')  # ugly but fast
                except Exception:
                    # Fall back to filename parsing
                    pass

                # Parse info from filename: name_id8_timestamp.logion.zip
                basename = os.path.basename(path)
                parts = basename.replace(".logion.zip", "").rsplit("_", 2)

                results.append({
                    "filename": basename,
                    "path": path,
                    "size_bytes": size,
                    "modified_at": mtime,
                    "project_name": parts[0].replace("_", " ") if len(parts) >= 3 else "?",
                    "project_id_short": parts[1] if len(parts) >= 3 else "?",
                })
            except Exception as e:
                logger.warning(f"Skipping backup {path}: {e}")
        return results

    # ── Restore ────────────────────────────────────────────────────

    def restore_project_from_zip(self, zip_data: bytes) -> Project:
        """Restore a project from a .logion.zip backup as a new project."""
        with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
            backup = json.loads(zf.read("backup.json").decode("utf-8"))

            # 1. Create new project with new ID
            p = backup["project"]
            new_project_id = str(uuid.uuid4())
            project = Project(
                id=new_project_id,
                filename=p["filename"],
                name=f"[Restored] {p.get('name') or p.get('filename', 'Project')}",
                status=p.get("status", "processing"),
                rag_status=p.get("rag_status", "ready"),
                source_lang=p.get("source_lang", "en"),
                target_lang=p.get("target_lang", "de"),
                use_clean_template=p.get("use_clean_template", False),
                use_ai=p.get("use_ai", False),
                file_hash=p.get("file_hash"),
                config=p.get("config"),
                ingestion_logs=p.get("ingestion_logs"),
                rag_progress=p.get("rag_progress", 100),
                archived=False,
                archive_folder=None,
                created_at=datetime.utcnow(),
            )
            self.db.add(project)

            # 2. Restore files — build old_id → new_id mapping
            file_id_map = {}
            for f_rec in backup.get("files", []):
                new_file_id = str(uuid.uuid4())
                file_id_map[f_rec["id"]] = new_file_id
                new_object_name = f"{new_project_id}/{f_rec['category']}/{f_rec['filename']}"

                # Extract physical file from ZIP if present
                arc_name = f"files/{f_rec['category']}/{f_rec['filename']}"
                try:
                    file_bytes = zf.read(arc_name)
                    upload_file(file_bytes, new_object_name)
                except KeyError:
                    logger.warning(f"Physical file not in backup: {arc_name}")

                pf = ProjectFile(
                    id=new_file_id,
                    project_id=new_project_id,
                    category=f_rec["category"],
                    filename=f_rec["filename"],
                    file_path=new_object_name,
                    uploaded_at=datetime.utcnow(),
                )
                self.db.add(pf)

            self.db.flush()

            # 3. Restore segments — build old_seg_id → new_seg_id mapping
            seg_id_map = {}
            for s in backup.get("segments", []):
                new_seg_id = str(uuid.uuid4())
                seg_id_map[s["id"]] = new_seg_id
                seg = Segment(
                    id=new_seg_id,
                    project_id=new_project_id,
                    file_id=file_id_map.get(s.get("file_id")),
                    index=s["index"],
                    source_content=s["source_content"],
                    target_content=s.get("target_content"),
                    status=s.get("status", "draft"),
                    metadata_json=s.get("metadata_json"),
                    embedding=s.get("embedding"),
                )
                self.db.add(seg)

            # 4. Restore glossary
            for e in backup.get("glossary_entries", []):
                ge = GlossaryEntry(
                    id=str(uuid.uuid4()),
                    project_id=new_project_id,
                    source_term=e["source_term"],
                    target_term=e["target_term"],
                    source_lemma=e.get("source_lemma", ""),
                    context_note=e.get("context_note"),
                    origin=e.get("origin", "manual"),
                    segment_id=seg_id_map.get(e.get("segment_id")),
                    created_at=datetime.utcnow(),
                )
                self.db.add(ge)

            # 5. Restore translation units
            for t in backup.get("translation_units", []):
                tu = TranslationUnit(
                    project_id=new_project_id,
                    source_hash=t["source_hash"],
                    source_text=t["source_text"],
                    target_text=t["target_text"],
                    origin_type=t.get("origin_type", "user"),
                    context_prev=t.get("context_prev"),
                    context_next=t.get("context_next"),
                )
                self.db.add(tu)

            # 6. Restore context chunks
            for c in backup.get("context_chunks", []):
                cc = ContextChunk(
                    id=str(uuid.uuid4()),
                    file_id=file_id_map.get(c.get("file_id")),
                    content=c["content"],
                    rich_content=c.get("rich_content"),
                    embedding=c.get("embedding"),
                    chunk_index=c.get("chunk_index"),
                    source_segment=c.get("source_segment"),
                    target_segment=c.get("target_segment"),
                    alignment_score=c.get("alignment_score"),
                    alignment_type=c.get("alignment_type"),
                )
                self.db.add(cc)

            # 7. Restore AI usage logs
            for u in backup.get("ai_usage_logs", []):
                log_entry = AiUsageLog(
                    id=str(uuid.uuid4()),
                    project_id=new_project_id,
                    segment_id=seg_id_map.get(u.get("segment_id")),
                    model=u.get("model", "unknown"),
                    trigger_type=u.get("trigger_type", "manual"),
                    input_tokens=u.get("input_tokens", 0),
                    output_tokens=u.get("output_tokens", 0),
                )
                self.db.add(log_entry)

            self.db.commit()
            self.db.refresh(project)
            return project
