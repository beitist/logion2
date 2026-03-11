import json
import re
import hashlib
import asyncio
import logging
import os
import google.generativeai as genai
import anthropic
from sqlalchemy.orm import Session
from ..models import GlossaryEntry
from ..glossary_service import get_nlp
from ..config import get_default_model_id, get_ai_models_config

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
    ) -> tuple[list[GlossaryEntry], dict]:
        """
        Extract glossary-worthy terms from a confirmed/pseudo-confirmed segment.
        Deletes previous auto-entries for this segment, stores new ones.
        Returns (list of newly created GlossaryEntry objects, usage dict).
        """
        # 1. Delete old auto-entries for this segment
        self._delete_auto_entries_for_segment(segment_id)

        # 2. Strip tags from input
        clean_source = re.sub(r"<[^>]+>", "", source_text).strip()
        clean_target = re.sub(r"<[^>]+>", "", target_text).strip()

        if not clean_source or not clean_target:
            return [], {}

        # 3. Extract terms via AI
        term_pairs, usage = await self._extract_terms_via_ai(
            clean_source, clean_target, topic, source_lang, target_lang, model_name
        )

        if not term_pairs:
            return [], usage

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

        # 5. Store new entries (with strict filtering)
        new_entries = []
        for pair in term_pairs:
            source = pair.get("source", "").strip()
            target = pair.get("target", "").strip()

            if not source or not target:
                continue
            # Skip if source and target are identical (same word in both languages)
            if source.lower() == target.lower():
                continue
            # Skip single-word entries that are too short (likely abbreviations/acronyms)
            if source.upper() == source and target.upper() == target and len(source) <= 6:
                continue  # Identical abbreviations (e.g. GIZ→GIZ, BMZ→BMZ)
            # Skip very short terms (1-2 chars) — rarely useful
            if len(source) <= 2:
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

        return new_entries, usage

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

    def _get_provider(self, model_name: str) -> str:
        """Looks up the provider for a model ID from ai_models.json."""
        config = get_ai_models_config()
        for m in config.get("models", []):
            if m["id"] == model_name:
                return m.get("provider", "google")
        return "google"

    async def _extract_terms_via_ai(
        self,
        source_text: str,
        target_text: str,
        topic: str,
        source_lang: str,
        target_lang: str,
        model_name: str = None,
    ) -> tuple[list[dict], dict]:
        """
        Calls the configured AI model to extract glossary-worthy term pairs.
        Returns: ([{"source": "...", "target": "..."}, ...], usage_dict)
        """
        if not model_name:
            model_name = get_default_model_id()

        topic_line = f"\nTopic/Domain: {topic}" if topic else ""

        prompt = f"""Extract glossary-worthy technical terms from this translation pair.

Source ({source_lang}): {source_text}
Target ({target_lang}): {target_text}{topic_line}

Rules:
1. Extract ONLY domain-specific or technical terms that a translator would need to know. NOT common words, NOT generic verbs, NOT obvious translations.
2. Return terms in their SINGULAR / INFINITIVE base form (e.g., "report" not "reports", "implement" not "implementing").
3. Include multi-word terms (e.g., "final report", "project implementation").
4. Each term pair must be a direct translation equivalent.
5. Maximum 3 term pairs per segment. Be very selective — only terms where consistency across a document matters.
6. SKIP terms where source and target are identical (abbreviations, proper nouns that stay the same).
7. SKIP generic terms like "project", "report", "country", "government", "year" etc.
8. Return valid JSON array: [{{"source": "term_{source_lang}", "target": "term_{target_lang}"}}]
9. If no glossary-worthy terms exist, return an empty array: []

Output ONLY the JSON array, no explanation."""

        try:
            provider = self._get_provider(model_name)

            if provider == "anthropic":
                text, usage = await self._call_claude(prompt, model_name)
            else:
                text, usage = await self._call_gemini(prompt, model_name)

            # Parse JSON robustly
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data, usage

            return [], usage

        except Exception as e:
            # Re-raise quota errors so the workflow can stop
            from ..rag.inference import QuotaExceededError
            if isinstance(e, QuotaExceededError):
                raise
            logger.error(f"Auto-glossary extraction failed: {e}")
            return [], {}

    async def _call_gemini(self, prompt: str, model_name: str) -> tuple[str, dict]:
        from ..rag.inference import QuotaExceededError, _is_quota_exceeded
        gm = genai.GenerativeModel(model_name)
        config = genai.GenerationConfig(temperature=0.1)

        try:
            if hasattr(gm, "generate_content_async"):
                res = await gm.generate_content_async(prompt, generation_config=config)
            else:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None, lambda: gm.generate_content(prompt, generation_config=config)
                )
            usage = {}
            if hasattr(res, 'usage_metadata') and res.usage_metadata:
                usage = {
                    "model": model_name,
                    "input_tokens": getattr(res.usage_metadata, 'prompt_token_count', 0),
                    "output_tokens": getattr(res.usage_metadata, 'candidates_token_count', 0),
                }
            return res.text.strip(), usage
        except Exception as e:
            if _is_quota_exceeded(str(e)):
                raise QuotaExceededError(f"API quota exceeded: {e}")
            raise

    async def _call_claude(self, prompt: str, model_name: str) -> tuple[str, dict]:
        from ..rag.inference import QuotaExceededError, _is_quota_exceeded
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            res = await client.messages.create(
                model=model_name,
                max_tokens=2048,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = {
                "model": model_name,
                "input_tokens": res.usage.input_tokens,
                "output_tokens": res.usage.output_tokens,
            }
            return res.content[0].text.strip(), usage
        except Exception as e:
            if _is_quota_exceeded(str(e)):
                raise QuotaExceededError(f"API quota exceeded: {e}")
            raise
