import json
import re
import hashlib
import asyncio
import logging
import os
import google.generativeai as genai
from sqlalchemy.orm import Session
from ..models import GlossaryEntry
from ..glossary_service import get_nlp
from ..config import get_default_model_id

logger = logging.getLogger("AutoGlossary")


def hash_content(text: str) -> str:
    """Stable hash for tracking whether target_content changed."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class AutoGlossaryService:
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.nlp = get_nlp()

        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)

    async def extract_and_store(
        self,
        segment_id: str,
        source_text: str,
        target_text: str,
        topic: str = "",
        source_lang: str = "en",
        target_lang: str = "de",
        model_name: str = None,
    ) -> list[GlossaryEntry]:
        """
        Extract glossary-worthy terms from a confirmed/pseudo-confirmed segment.
        Deletes previous auto-entries for this segment, stores new ones.
        Returns list of newly created GlossaryEntry objects.
        """
        # 1. Delete old auto-entries for this segment
        self._delete_auto_entries_for_segment(segment_id)

        # 2. Strip tags from input
        clean_source = re.sub(r"<[^>]+>", "", source_text).strip()
        clean_target = re.sub(r"<[^>]+>", "", target_text).strip()

        if not clean_source or not clean_target:
            return []

        # 3. Extract terms via AI
        term_pairs = await self._extract_terms_via_ai(
            clean_source, clean_target, topic, source_lang, target_lang, model_name
        )

        if not term_pairs:
            return []

        # 4. Deduplicate against existing manual entries
        existing_manual = set()
        for (src,) in self.db.query(GlossaryEntry.source_term).filter(
            GlossaryEntry.project_id == self.project_id,
            GlossaryEntry.origin == "manual",
        ).all():
            existing_manual.add(src.lower().strip())

        # Also deduplicate against existing auto-entries from OTHER segments
        existing_auto = set()
        for (src,) in self.db.query(GlossaryEntry.source_term).filter(
            GlossaryEntry.project_id == self.project_id,
            GlossaryEntry.origin == "auto",
            GlossaryEntry.segment_id != segment_id,
        ).all():
            existing_auto.add(src.lower().strip())

        # 5. Store new entries
        new_entries = []
        for pair in term_pairs:
            source = pair.get("source", "").strip()
            target = pair.get("target", "").strip()

            if not source or not target:
                continue
            if source.lower() in existing_manual:
                continue  # Don't shadow manual entries
            if source.lower() in existing_auto:
                continue  # Already extracted from another segment

            # Compute lemma via SpaCy
            doc = self.nlp(source.lower())
            lemma = " ".join([t.lemma_ for t in doc])

            entry = GlossaryEntry(
                project_id=self.project_id,
                source_term=source,
                target_term=target,
                source_lemma=lemma,
                context_note="Auto-extracted",
                origin="auto",
                segment_id=segment_id,
            )
            self.db.add(entry)
            new_entries.append(entry)

        if new_entries:
            self.db.commit()
            logger.info(f"Auto-glossary: Stored {len(new_entries)} terms for segment {segment_id}")

        return new_entries

    def _delete_auto_entries_for_segment(self, segment_id: str):
        """Delete all auto-glossary entries linked to a specific segment."""
        deleted = self.db.query(GlossaryEntry).filter(
            GlossaryEntry.project_id == self.project_id,
            GlossaryEntry.origin == "auto",
            GlossaryEntry.segment_id == segment_id,
        ).delete(synchronize_session="fetch")

        if deleted > 0:
            self.db.commit()
            logger.info(f"Auto-glossary: Deleted {deleted} old entries for segment {segment_id}")

    async def _extract_terms_via_ai(
        self,
        source_text: str,
        target_text: str,
        topic: str,
        source_lang: str,
        target_lang: str,
        model_name: str = None,
    ) -> list[dict]:
        """
        Calls Gemini to extract glossary-worthy term pairs.
        Returns: [{"source": "...", "target": "..."}, ...]
        """
        if not model_name:
            model_name = get_default_model_id()

        topic_line = f"\nTopic/Domain: {topic}" if topic else ""

        prompt = f"""Extract glossary-worthy technical terms from this translation pair.

Source ({source_lang}): {source_text}
Target ({target_lang}): {target_text}{topic_line}

Rules:
1. Extract ONLY domain-specific or technical terms, NOT common words.
2. Return terms in their SINGULAR / INFINITIVE base form (e.g., "report" not "reports", "implement" not "implementing").
3. Include multi-word terms (e.g., "final report", "project implementation").
4. Each term pair must be a direct translation equivalent.
5. Maximum 5 term pairs per segment.
6. Return valid JSON array: [{{"source": "term_{source_lang}", "target": "term_{target_lang}"}}]
7. If no glossary-worthy terms exist, return an empty array: []

Output ONLY the JSON array, no explanation."""

        try:
            gm = genai.GenerativeModel(model_name)
            config = genai.GenerationConfig(temperature=0.1)

            if hasattr(gm, "generate_content_async"):
                res = await gm.generate_content_async(prompt, generation_config=config)
            else:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None, lambda: gm.generate_content(prompt, generation_config=config)
                )

            text = res.text.strip()

            # Parse JSON robustly
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data

            return []

        except Exception as e:
            logger.error(f"Auto-glossary extraction failed: {e}")
            return []
