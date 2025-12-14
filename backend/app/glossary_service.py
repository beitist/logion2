
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
            doc = self.nlp(entry.source_term)
            self.matcher.add(entry.id, [doc])

    def find_matches(self, text: str) -> List[Dict]:
        """
        Finds glossary terms in the text.
        Returns unique list of matches: [{'term': 'Final Report', 'target': '...', 'note': '...'}]
        """
        if not text: return []
        
        doc = self.nlp(text)
        matches = self.matcher(doc)
        
        results = []
        seen_ids = set()
        
        for match_id, start, end in matches:
            entry_id = self.nlp.vocab.strings[match_id]
            
            if entry_id in seen_ids:
                continue
                
            entry = self.entries_map.get(str(entry_id)) # match_id might be hash int? No, we add string ID. 
            # Wait, matcher.add takes string ID. But returns hash in loop.
            # So match_id is int hash. string_id = vocab.strings[match_id]
            
            # Actually, `match_id` in the loop is the int hash.
            eid_str = self.nlp.vocab.strings[match_id]
            
            if eid_str in self.entries_map:
                entry = self.entries_map[eid_str]
                results.append({
                    "source": entry.source_term,
                    "target": entry.target_term,
                    "note": entry.context_note
                })
                seen_ids.add(eid_str)
                
        return results

    def add_term(self, source: str, target: str, note: str = None) -> GlossaryEntry:
        """
        Adds a term to DB and computes lemma.
        """
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
