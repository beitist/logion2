import os
from typing import List, Dict
from sentence_transformers import SentenceTransformer
import torch

from ..database import SessionLocal, engine
from ..models import TranslationMemoryUnit, Base

# Force CPU (MPS is unstable for some torch ops on Mac)
# set this before loading model
os.environ["IT_HAS_MPS"] = "0" 

class TranslationMemory:
    def __init__(self):
        # Initialize Database Table if not exists (Usually main.py handles this, but unsure of startup order)
        # Base.metadata.create_all(bind=engine) 
        
        # Initialize Embedding Model
        # Force CPU
        self.device = "cpu"
        self.model = SentenceTransformer("all-MiniLM-L6-v2", device=self.device)
        
    def _generate_embedding(self, text: str) -> List[float]:
        return self.model.encode(text).tolist()

    def add_segment(self, source_text: str, target_text: str, source_lang: str, target_lang: str):
        """
        Adds a translation pair to the Postgres Vector DB.
        """
        # CLEANING FOR EMBEDDING ONLY (Strip tags and tabs)
        import re
        # Remove XML tags like <1>, </1>, <ph .../>
        stripped_source = re.sub(r'<[^>]+>', '', source_text)
        # Remove Tabs
        stripped_source = stripped_source.replace('\t', ' ')
        # Collapse multiple spaces
        stripped_source = re.sub(r'\s+', ' ', stripped_source).strip()
        
        if not stripped_source:
             return # Skip empty content

        # Generate embedding
        emb = self._generate_embedding(stripped_source)
        
        # Save to DB
        db = SessionLocal()
        try:
            tm_unit = TranslationMemoryUnit(
                source_text=stripped_source,
                target_text=target_text,
                raw_source=source_text,
                source_lang=source_lang,
                target_lang=target_lang,
                embedding=emb
            )
            db.add(tm_unit)
            db.commit()
        except Exception as e:
            print(f"Error saving to TM: {e}")
            db.rollback()
        finally:
            db.close()

    def search_similar(self, source_text: str, n_results: int = 3) -> List[Dict]:
        """
        Returns similar segments using pgvector L2 distance.
        """
        # CLEANING FOR QUERY EMBEDDING ONLY
        import re
        stripped_query = re.sub(r'<[^>]+>', '', source_text)
        stripped_query = stripped_query.replace('\t', ' ')
        stripped_query = re.sub(r'\s+', ' ', stripped_query).strip()
        
        if not stripped_query:
            return []

        # Generate embedding
        query_emb = self._generate_embedding(stripped_query)
        
        db = SessionLocal()
        try:
            # Query Logic: Order by L2 distance (Euclidean)
            # using the <=> operator or l2_distance function helper
            # SQLAlchemy pgvector syntax: TranslationMemoryUnit.embedding.l2_distance(query_emb)
            
            results = db.query(TranslationMemoryUnit).order_by(
                TranslationMemoryUnit.embedding.l2_distance(query_emb)
            ).limit(n_results).all()
            
            hits = []
            for unit in results:
                # Calculate simple distance Score for display if needed?
                # For now just return content.
                hits.append({
                    "source": unit.raw_source, # Return RAW source for display parity
                    "target": unit.target_text,
                    "distance": 0.0 # We'd need to select distance explicitly to get it, skipping for now to save complexity
                })
            return hits
            
        except Exception as e:
            print(f"Error searching TM: {e}")
            return []
        finally:
            db.close()
