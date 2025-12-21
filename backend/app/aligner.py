
import spacy
import re
import numpy as np
from sentence_transformers import util

class SemanticAligner:
    def __init__(self, encoder_model):
        """
        :param encoder_model: SentenceTransformer model (LaBSE) loaded primarily in rag.py
        """
        self.encoder = encoder_model
        self.nlp_en = None
        self.nlp_de = None
        
        # Load spaCy models lazily
        try:
            print("Loading SpaCy Transformer Models (this may take a moment)...")
            self.nlp_en = spacy.load("en_core_web_trf")
            self.nlp_de = spacy.load("de_dep_news_trf")
            print("✅ SpaCy Models Loaded.")
        except Exception as e:
            print(f"❌ Failed to load SpaCy models: {e}. Falling back to splitting by newline/pysbd if needed.")

    def protect_tags(self, text):
        """
        Replaces <1> with __TAG_1__ to prevent spaCy from splitting it.
        Returns: (protected_text, mapping_dict)
        """
        tag_map = {}
        
        def repl(match):
            # match.group(0) is full tag e.g. <1>
            # Create a safe token
            token = f"__TAG_{len(tag_map)}__"
            tag_map[token] = match.group(0)
            return f" {token} " # Add spaces to ensure it's tokenized separately

        # Regex for <N>, </N>, <N />, [TAB]
        # We need to cover the <1> and </1> patterns
        pattern = re.compile(r'<[^>]+>')
        protected_text = pattern.sub(repl, text)
        return protected_text, tag_map

    def restore_tags(self, text, tag_map):
        """
        Restores __TAG_1__ to <1>, removing the padding spaces we added.
        """
        for token, original in tag_map.items():
            # We added " {token} ". So we look for that first to remove spaces.
            # But spaCy might have moved it or changed whitespace.
            # Safe approach: Replace the token, then fix specific spacing artifacts?
            # Or just replace the token string directly?
            # If we replace " __TAG_0__ " with "<1>", we lose the spaces we added.
            
            # Use regex to handle optional surrounding spaces
            # escape token for regex
            import re
            ptoken = re.escape(token)
            # Replace token surrounded by optional whitespace with original
            # NOTE: usage of " {token} " in protect_tags implies we prefer to collapse it back.
            # But what if there WAS a space?
            # "Click<1>" -> "Click __TAG__" -> "Click<1>"
            # "Click <1>" -> "Click  __TAG__" -> "Click <1>"
            
            # Let's simple-replace the token first, then handle the added spaces logic?
            # No, text.replace(token, original) leaves the spaces we added.
            
            # Try to replace " {token} " first (ideal case)
            if f" {token} " in text:
                text = text.replace(f" {token} ", original)
            elif f"{token} " in text:
                 text = text.replace(f"{token} ", original)
            elif f" {token}" in text:
                 text = text.replace(f" {token}", original)
            else:
                 text = text.replace(token, original)
                 
        return text.strip()

    def segment_text(self, text, lang="en"):
        """
        Uses spaCy transformer to split sentences.
        """
        if not text or not text.strip(): return []
        
        # 1. Protect Tags
        protected, tag_map = self.protect_tags(text)
        
        # 2. Tokenize/Segment
        nlp = self.nlp_en if lang == "en" else self.nlp_de
        if not nlp:
             # Fallback
             return [t.strip() for t in protected.split('\n') if t.strip()]

        doc = nlp(protected)
        sentences = [sent.text.strip() for sent in doc.sents]
        
        # 3. Restore Tags
        restored = [self.restore_tags(s, tag_map) for s in sentences if s.strip()]
        return restored

    def align(self, source_text, target_text):
        """
         aligns source and target text using 1:1, 2:1, 1:2 logic.
         Returns list of { 'source': str, 'target': str, 'score': float, 'type': str }
        """
        if not source_text or not target_text: return []

        # FAST PATH for simple 1:1 lines (common in TMX)
        # If text is short and has no typical sentence splitters, return 1:1 immediately
        # This avoids the expensive Transformer call for 95% of cases.
        def is_simple(t):
             if len(t) > 300: return False
             if "\n" in t: return False
             # If it contains multiple periods/questions followed by space+upper
             import re
             if re.search(r'[.?!]\s+[A-Z]', t): return False
             return True

        if is_simple(source_text) and is_simple(target_text):
             # Just return 1:1
             return [{
                 "source": source_text,
                 "target": target_text,
                 "score": 100,
                 "type": "1:1" 
             }]

        # 1. Segment
        src_sents = self.segment_text(source_text, "en")
        tgt_sents = self.segment_text(target_text, "de")
        
        if not src_sents or not tgt_sents:
            return []

        # 2. Embed all sentences
        src_vecs = self.encoder.encode(src_sents, convert_to_tensor=True)
        tgt_vecs = self.encoder.encode(tgt_sents, convert_to_tensor=True)
        
        aligned_pairs = []
        i = 0
        j = 0
        
        # Threshold to accept a match
        MIN_SCORE = 0.65 
        
        while i < len(src_sents) and j < len(tgt_sents):
            # Candidates
            s1 = src_sents[i]
            t1 = tgt_sents[j]
            
            # Vectors
            v_s1 = src_vecs[i]
            v_t1 = tgt_vecs[j]
            
            # 1:1 Score
            sim_1_1 = util.cos_sim(v_s1, v_t1).item()
            
            # 2:1 Score (Source is split) -> Merge Source i + i+1
            sim_2_1 = -1.0
            if i + 1 < len(src_sents):
                s2 = src_sents[i] + " " + src_sents[i+1]
                # Re-embed combined (a bit expensive but accurate)
                v_s2 = self.encoder.encode(s2, convert_to_tensor=True)
                sim_2_1 = util.cos_sim(v_s2, v_t1).item()
                
            # 1:2 Score (Target is split) -> Merge Target j + j+1
            sim_1_2 = -1.0
            if j + 1 < len(tgt_sents):
                t2 = tgt_sents[j] + " " + tgt_sents[j+1]
                v_t2 = self.encoder.encode(t2, convert_to_tensor=True)
                sim_1_2 = util.cos_sim(v_s1, v_t2).item()
                
            # Decision
            best_score = max(sim_1_1, sim_2_1, sim_1_2)
            
            if best_score < MIN_SCORE:
                aligned_pairs.append({
                    "source": s1,
                    "target": t1,
                    "score": int(sim_1_1 * 100),
                    "type": "1:1" # Low confidence
                })
                i += 1
                j += 1
                continue

            if best_score == sim_2_1:
                aligned_pairs.append({
                    "source": src_sents[i] + " " + src_sents[i+1],
                    "target": t1,
                    "score": int(sim_2_1 * 100),
                    "type": "2:1"
                })
                i += 2
                j += 1
            elif best_score == sim_1_2:
                aligned_pairs.append({
                    "source": s1,
                    "target": tgt_sents[j] + " " + tgt_sents[j+1],
                    "score": int(sim_1_2 * 100),
                    "type": "1:2"
                })
                i += 1
                j += 2
            else:
                aligned_pairs.append({
                    "source": s1,
                    "target": t1,
                    "score": int(sim_1_1 * 100),
                    "type": "1:1"
                })
                i += 1
                j += 1
                
        return aligned_pairs
