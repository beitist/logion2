
import spacy
from spacy.matcher import PhraseMatcher
from sqlalchemy.orm import Session
from .models import GlossaryEntry
from typing import List, Dict

# Singleton/Global cache for the model to avoid reloading
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            # Prefer TRF for accuracy if available (from parser)
            _nlp = spacy.load("en_core_web_trf")
        except:
            # Fallback
            _nlp = spacy.load("en_core_web_sm")
    return _nlp

class GlossaryMatcher:
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.nlp = get_nlp()
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LEMMA")
        self._load_entries()

    def _load_entries(self):
        """Loads entries from DB into SpaCy Matcher"""
        entries = self.db.query(GlossaryEntry).filter(GlossaryEntry.project_id == self.project_id).all()
        self.entries_map = {} # Hash -> Entry
        
        patterns = []
        for entry in entries:
            # We match against the 'source_lemma' ideally, but PhraseMatcher (attr="LEMMA") 
            # computes lemma of doc vs patterns.
            # So pattern should be a Doc object created from the lemma string or term.
            # Best practice: Create Doc from the TERM, let SpaCy compute its lemma, matches Doc's lemma.
            
            # CRITICAL FIX: Use nlp() not make_doc() so lemmas are computed for the pattern too!
            # Also force lowercase to avoid Proper Noun lemma retention
            pattern_doc = self.nlp(entry.source_term.lower())
            patterns.append(pattern_doc)
            print(f"DEBUG Loaded Pattern: '{entry.source_term}' -> Lemmas: {[t.lemma_ for t in pattern_doc]}")
            
            # Map the pattern string (or hash) back to the entry
            # Note: PhraseMatcher returns match_id, start, end. match_id is the string ID.
            # We use entry.id as the match ID.
            self.entries_map[entry.id] = entry
            
        # Add all to matcher
        # We need to associate IDs. PhraseMatcher.add accepts lists of docs.
        # We can't easily map exact pattern back if we batch add.
        # So we add one by one with ID.
        for entry in entries:
             # Create a Doc from the source term with FULL pipelne (lemmatizer)
            # Force lowercase for robust lemma matching (SpaCy proper nouns keep case otherwise)
            doc = self.nlp(entry.source_term.lower())
            self.matcher.add(entry.id, [doc])

    def find_matches(self, text: str) -> List[Dict]:
        """
        Finds glossary terms in the text.
        Returns unique list of matches: [{'term': 'Final Report', 'target': '...', 'note': '...'}]
        """
        if not text: return []
        
        # Strip XML tags <...> to ensure contiguous matching (e.g. <1>Final</1> <2>Report</2>)
        import re
        clean_text = re.sub(r'<[^>]+>', '', text)
        # Normalize whitespace (replace multiple spaces/newlines with single space)
        # Also LOWERCASE to ensure lemma matching works against our lowercase patterns
        clean_text = re.sub(r'\s+', ' ', clean_text).strip().lower()
        
        doc = self.nlp(clean_text)
        matches = self.matcher(doc)
        
        results = []
        seen_ids = set()
        
        for match_id, start, end in matches:
            # match_id is the hash, we need the string ID
            # In add_term, we used entry.id (string) as match_id
            # SpaCy stores string IDs in vocab
            string_id = self.nlp.vocab.strings[match_id]
            entry = self.entries_map.get(string_id)
            
            if entry:
                results.append({
                    "source": entry.source_term,
                    "target": entry.target_term,
                    "note": entry.context_note,
                    "origin": getattr(entry, "origin", "manual"),
                })
        
        # Dedup based on source term
        deduped = []
        seen = set()
        for r in results:
            if r['source'] not in seen:
                deduped.append(r)
                seen.add(r['source'])
                
        return deduped

    def add_term(self, source: str, target: str, note: str = None) -> GlossaryEntry:
        """
        Adds a term to DB and computes lemma.
        """
        # Sanitize Input
        source = source.strip()
        target = target.strip()
        
        doc = self.nlp(source)
        lemma = " ".join([t.lemma_ for t in doc])
        
        entry = GlossaryEntry(
            project_id=self.project_id,
            source_term=source,
            target_term=target,
            source_lemma=lemma,
            context_note=note
        )
        self.db.add(entry)
        self.db.commit()
        
        # Update in-memory matcher
        # Same logic as _load_entries
        # Force lowercase for robust lemma matching (SpaCy proper nouns keep case otherwise)
        pattern_doc = self.nlp(entry.source_term.lower())
        self.entries_map[entry.id] = entry
        self.matcher.add(entry.id, [pattern_doc])
        
        return entry
