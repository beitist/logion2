import math
import re

class ScoringEngine:
    """
    Centralized logic for converting Raw Retrieval Logits into User-Facing Scores (0-100%).
    Focuses on penalties for mismatches (Numbers, Length, Grammatical Completeness).
    """

    @staticmethod
    def calculate_score(query_text: str, match_text: str, raw_logit: float, nlp_model=None) -> tuple[int, list[str]]:
        """
        Calculates the final UI score based on semantic similarity and heuristic penalties.
        
        :param query_text: The source segment (search query).
        :param match_text: The retrieved translation memory source.
        :param raw_logit: The raw output from the Cross-Encoder.
        :param nlp_model: Optional SpaCy model (for language specific checks).
        :return: (score_percent, list_of_applied_penalties)
        """
        penalties = []
        
        # 1. Base Score Calculation (Sigmoid)
        # We assume the Cross-Encoder is trained such that >4.0 is perfect, >2.5 is very good, <0 is poor.
        if raw_logit > 4.0:
            ui_score = 99.0
        elif raw_logit > 2.5:
             # Aggressive sigmoid for good matches
             # Logit 2.5 -> 1 / (1 + exp(-(2.5))) = 92%
             ui_score = 1 / (1 + math.exp(-(raw_logit - 0.0))) * 100
        else:
             # Standard curve for weaker matches
             ui_score = 1 / (1 + math.exp(-(raw_logit - 0.0))) * 100

        # We only apply strict penalties if the base score is high enough to matter (e.g. >80%)
        # If it's already 50%, forcing it to 45% doesn't change the UI behavior much (it's "Fuzzy").
        # Using 80% as a safe lower bound for "High Quality" logic.
        if ui_score > 80:
            
            # 2. Number Integrity Check
            # Extract numbers from both strings. If they differ, penalize HEAVILY.
            # Rationale: "20 degrees" vs "50 degrees" is a critical translation error.
            nums_query = set(re.findall(r'\d+', query_text))
            nums_match = set(re.findall(r'\d+', match_text))
            if nums_query != nums_match:
                # 99 -> 74 (Drop below "High Fuzzy" threshold)
                # But we use a calculated penalty to be smooth.
                ui_score -= 25.0 
                penalties.append("number_mismatch")

            # 3. Length-Based Precision Decay (Prevent Truncation Optimism)
            # Threshold 1.25 allows for normal translation expansion (~25%).
            # Beyond that, we assume content is missing or added.
            try:
                l_query = len(query_text)
                l_match = len(match_text)
                # Avoid div by zero
                ratio = l_match / max(l_query, 1) if l_match > l_query else l_query / max(l_match, 1)
                
                THRESHOLD = 1.25
                if ratio > THRESHOLD:
                    # Linear penalty: (Ratio - 1.25) * 100
                    # 1.30 -> (0.05 * 100) = 5% penalty
                    # 1.50 -> (0.25 * 100) = 25% penalty
                    len_penalty = (ratio - THRESHOLD) * 100
                    ui_score -= len_penalty
                    penalties.append(f"length_ratio_{ratio:.2f}")
            except:
                pass

            # 4. Linguistic Completeness Penalty (Fragment Detection)
            # If the query looks like a fragment (ends in DET, ADP, PRON), penalize.
            # Only checking Query for now (as that's what we are matching AGAINST).
            # Using SpaCy if available.
            if ui_score > 90 and nlp_model:
                try:
                    # Determine which NLP to use? 
                    # We passed 'nlp_model' which is likely the Aligner wrapper or a specific model.
                    # For simplicity, we assume the caller provided the CORRECT language model (DE usually).
                    
                    # Heuristic: Check if text contains German determiners to guess.
                    # Or rely on caller.
                    
                    # Let's assume nlp_model is a callable spaCy pipeline
                    doc = nlp_model(query_text)
                    if len(doc) > 0:
                        # Find last non-punct token
                        last_token = None
                        for token in reversed(doc):
                            if token.pos_ not in ["PUNCT", "SPACE"]:
                                last_token = token
                                break
                        
                        if last_token:
                             # STOP classes: DET, ADP, CONJ, PRON
                             if last_token.pos_ in ["DET", "ADP", "CCONJ", "SCONJ", "PRON"]:
                                 ui_score -= 5.0
                                 penalties.append(f"fragment_{last_token.pos_}")
                except Exception:
                    # Fail silent on NLP errors
                    pass

        # Clamp
        ui_score = max(0, min(99, ui_score))
        
        return int(ui_score), penalties
