
import re
import spacy
from spacy.matcher import PhraseMatcher
from sqlalchemy.orm import Session
from .models import GlossaryEntry
from typing import List, Dict
from .logger import get_logger

logger = get_logger("Glossary")

# Singleton/Global cache for the SpaCy model
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_trf")
        except:
            _nlp = spacy.load("en_core_web_sm")
    return _nlp

# Module-level cache: {project_id: {"count": N, "matcher": PhraseMatcher, "entries": {id: {...}}}}
_matcher_cache: Dict[str, dict] = {}


class GlossaryMatcher:
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.nlp = get_nlp()
        self._load_or_reuse()

    def _load_or_reuse(self):
        """Reuses cached PhraseMatcher if entry count hasn't changed, otherwise rebuilds."""
        db_count = self.db.query(GlossaryEntry).filter(
            GlossaryEntry.project_id == self.project_id
        ).count()

        cached = _matcher_cache.get(self.project_id)
        if cached and cached["count"] == db_count:
            self.matcher = cached["matcher"]
            self.entries_data = cached["entries"]
            return

        # Rebuild
        self._build_matcher()

    def _build_matcher(self):
        """Loads entries from DB, builds SpaCy PhraseMatcher, and caches the result."""
        entries = self.db.query(GlossaryEntry).filter(
            GlossaryEntry.project_id == self.project_id
        ).all()

        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LEMMA")
        self.entries_data = {}

        for entry in entries:
            # Store as plain dict (not ORM objects) for cache safety
            self.entries_data[entry.id] = {
                "source_term": entry.source_term,
                "target_term": entry.target_term,
                "context_note": entry.context_note,
                "origin": getattr(entry, "origin", "manual"),
            }
            doc = self.nlp(entry.source_term.lower())
            self.matcher.add(entry.id, [doc])

        # Cache it
        _matcher_cache[self.project_id] = {
            "count": len(entries),
            "matcher": self.matcher,
            "entries": self.entries_data,
        }
        logger.info(f"Built GlossaryMatcher for {self.project_id}: {len(entries)} entries")

    def find_matches(self, text: str) -> List[Dict]:
        """
        Finds glossary terms in the text.
        Returns unique list of matches: [{'source': '...', 'target': '...', 'note': '...'}]
        """
        if not text:
            return []

        # Strip XML tags and normalize whitespace + lowercase
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip().lower()

        doc = self.nlp(clean_text)
        matches = self.matcher(doc)

        results = []
        for match_id, start, end in matches:
            string_id = self.nlp.vocab.strings[match_id]
            entry = self.entries_data.get(string_id)
            if entry:
                results.append({
                    "entry_id": string_id,
                    "source": entry["source_term"],
                    "target": entry["target_term"],
                    "note": entry["context_note"],
                    "origin": entry["origin"],
                })

        # Dedup based on source term
        seen = set()
        deduped = []
        for r in results:
            if r['source'] not in seen:
                deduped.append(r)
                seen.add(r['source'])
        return deduped

    def add_term(self, source: str, target: str, note: str = None) -> GlossaryEntry:
        """Adds a term to DB, updates in-memory matcher and cache."""
        source = source.strip()
        target = target.strip()

        doc = self.nlp(source)
        lemma = " ".join([t.lemma_ for t in doc])

        entry = GlossaryEntry(
            project_id=self.project_id,
            source_term=source,
            target_term=target,
            source_lemma=lemma,
            context_note=note,
        )
        self.db.add(entry)
        self.db.commit()

        # Update in-memory matcher + cache
        pattern_doc = self.nlp(entry.source_term.lower())
        self.entries_data[entry.id] = {
            "source_term": entry.source_term,
            "target_term": entry.target_term,
            "context_note": entry.context_note,
            "origin": getattr(entry, "origin", "manual"),
        }
        self.matcher.add(entry.id, [pattern_doc])

        # Update cache
        _matcher_cache[self.project_id] = {
            "count": len(self.entries_data),
            "matcher": self.matcher,
            "entries": self.entries_data,
        }

        return entry


def invalidate_glossary_cache(project_id: str):
    """Call this when glossary entries are deleted/updated externally."""
    _matcher_cache.pop(project_id, None)
